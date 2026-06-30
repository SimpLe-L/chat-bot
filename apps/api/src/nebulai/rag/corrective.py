import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass
from dataclasses import replace
from typing import Any, Literal

from nebulai.core.config import settings
from nebulai.rag.schemas import RagSource

RewriteStrategy = Literal["none", "step_back", "hyde", "complex"]


@dataclass(frozen=True)
class RelevanceAssessment:
    score: float
    needs_rewrite: bool
    strategy: RewriteStrategy
    reason: str
    rewritten_queries: list[str]
    grader_provider: str = "deterministic"
    grader_message: str = "Deterministic corrective planner used."

    @property
    def rewritten_query(self) -> str:
        return self.rewritten_queries[0] if self.rewritten_queries else ""


def assess_relevance(question: str, sources: list[RagSource]) -> RelevanceAssessment:
    if not sources:
        return RelevanceAssessment(
            score=0.0,
            needs_rewrite=True,
            strategy="hyde",
            reason="初次检索没有返回候选来源，触发 HyDE 假设答案检索。",
            rewritten_queries=[build_hyde_query(question), build_step_back_query(question)],
        )

    lexical_score = _lexical_overlap(question, " ".join(_source_context(source) for source in sources[:3]))
    vector_score = max((source.rerankScore or source.score or 0.0 for source in sources), default=0.0)
    score = max(lexical_score, min(vector_score, 1.0))

    strategy = choose_rewrite_strategy(question)
    if score < 0.18 or (strategy == "complex" and score < 0.6):
        return RelevanceAssessment(
            score=score,
            needs_rewrite=True,
            strategy=strategy,
            reason=f"初次检索相关性评分较低（{score:.2f}），触发 {strategy} 二次检索。",
            rewritten_queries=build_rewrite_queries(question, strategy),
        )

    return RelevanceAssessment(
        score=score,
        needs_rewrite=False,
        strategy="none",
        reason=f"初次检索相关性评分为 {score:.2f}，暂不触发二次检索。",
        rewritten_queries=[question],
    )


async def assess_relevance_with_llm(question: str, sources: list[RagSource]) -> RelevanceAssessment:
    fallback = assess_relevance(question, sources)
    if not _remote_llm_enabled():
        return fallback

    try:
        return await asyncio.to_thread(_llm_assess_relevance, question, sources)
    except Exception as exc:
        return replace(
            fallback,
            grader_provider="deterministic",
            grader_message=f"LLM corrective grader failed; deterministic planner used: {exc}",
        )


def assessment_from_llm_content(question: str, content: str) -> RelevanceAssessment:
    payload = _extract_json_object(content)
    strategy = _normalize_strategy(str(payload.get("strategy", "none")))
    score = _clamp_score(payload.get("score", 0.0))
    needs_rewrite = bool(payload.get("needs_rewrite", strategy != "none" or score < 0.18))
    rewritten_queries = [
        str(item).strip()
        for item in payload.get("rewritten_queries", [])
        if str(item).strip()
    ][:4]

    if needs_rewrite and not rewritten_queries:
        rewritten_queries = build_rewrite_queries(question, strategy if strategy != "none" else "step_back")
    if not needs_rewrite:
        strategy = "none"
        rewritten_queries = [question]

    return RelevanceAssessment(
        score=score,
        needs_rewrite=needs_rewrite,
        strategy=strategy,
        reason=str(payload.get("reason") or "LLM corrective grader completed."),
        rewritten_queries=rewritten_queries,
        grader_provider="openai-compatible",
        grader_message=f"LLM corrective grader completed with model {settings.llm_model}.",
    )


def choose_rewrite_strategy(question: str) -> RewriteStrategy:
    normalized = " ".join(question.split())
    complex_markers = ("并且", "以及", "分别", "对比", "多个", "多跳", "同时")
    if len(normalized) > 80 or any(marker in normalized for marker in complex_markers):
        return "complex"
    return "step_back"


def build_rewrite_queries(question: str, strategy: RewriteStrategy) -> list[str]:
    if strategy == "hyde":
        return [build_hyde_query(question), build_step_back_query(question)]
    if strategy == "complex":
        normalized = " ".join(question.split())
        return [
            f"拆解子问题一：{normalized} 的核心定义、背景和约束",
            f"拆解子问题二：{normalized} 的流程、影响因素、对比关系和结论",
            build_step_back_query(question),
        ]
    if strategy == "step_back":
        return [build_step_back_query(question)]
    return [question]


def build_step_back_query(question: str) -> str:
    normalized = " ".join(question.split())
    return f"从业务背景、定义、流程和约束角度补充检索：{normalized}"


def build_hyde_query(question: str) -> str:
    normalized = " ".join(question.split())
    return f"假设答案可能包含的关键事实、术语和上下文：{normalized}"


def merge_sources(*source_groups: list[RagSource]) -> list[RagSource]:
    merged: list[RagSource] = []
    seen: set[str] = set()
    for sources in source_groups:
        for source in sources:
            key = source.chunkId
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
    return merged


def _lexical_overlap(question: str, context: str) -> float:
    question_terms = set(_terms(question))
    if not question_terms:
        return 0.0
    context_terms = set(_terms(context))
    if not context_terms:
        return 0.0
    return len(question_terms & context_terms) / len(question_terms)


def _terms(text: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    return [term for term in normalized.split() if len(term) > 1]


def _remote_llm_enabled() -> bool:
    return settings.llm_provider in {"openai", "openai-compatible"} and bool(settings.effective_llm_api_key)


def _llm_assess_relevance(question: str, sources: list[RagSource]) -> RelevanceAssessment:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 RAG 检索质量评估器。只输出 JSON，不要输出 Markdown。"
                "字段：score(0-1), needs_rewrite(boolean), strategy(none|step_back|hyde|complex), "
                "reason(string), rewritten_queries(string array, max 4)。"
                "低相关、无来源或复杂多跳问题应 needs_rewrite=true。"
            ),
        },
        {
            "role": "user",
            "content": _build_grader_prompt(question, sources),
        },
    ]
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": False,
        "temperature": 0,
    }
    request = urllib.request.Request(
        url=f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.effective_llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"]
    return assessment_from_llm_content(question, content)


def _build_grader_prompt(question: str, sources: list[RagSource]) -> str:
    excerpts = "\n\n".join(
        f"[{index + 1}] score={source.score} rerank={source.rerankScore} title={source.documentTitle}\n{_source_context(source)[:900]}"
        for index, source in enumerate(sources[:5])
    ) or "无候选来源"
    return f"用户问题：{question}\n\n候选来源：\n{excerpts}\n\n请评估是否需要改写查询。"


def _source_context(source: RagSource) -> str:
    return source.context or source.excerpt


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).removesuffix("```").strip()
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM grader did not return a JSON object.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM grader JSON is not an object.")
    return parsed


def _normalize_strategy(value: str) -> RewriteStrategy:
    if value in {"none", "step_back", "hyde", "complex"}:
        return value  # type: ignore[return-value]
    return "step_back"


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))
