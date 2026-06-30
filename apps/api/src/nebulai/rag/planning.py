import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass
from dataclasses import replace
from typing import Any, Literal

from nebulai.core.config import settings

QuestionComplexity = Literal["simple", "multi_hop", "comparison", "broad_summary"]


@dataclass(frozen=True)
class QuestionPlan:
    complexity: QuestionComplexity
    sub_questions: list[str]
    planner_provider: str = "deterministic"
    planner_message: str = "Deterministic question planner used."

    @property
    def is_complex(self) -> bool:
        return self.complexity != "simple" and len(self.sub_questions) > 1


def plan_question(question: str) -> QuestionPlan:
    normalized = " ".join(question.split())
    complexity = classify_question(normalized)
    sub_questions = decompose_question(normalized, complexity)
    return QuestionPlan(complexity=complexity, sub_questions=sub_questions)


async def plan_question_with_llm(question: str) -> QuestionPlan:
    fallback = plan_question(question)
    if not _remote_llm_enabled():
        return fallback

    try:
        return await asyncio.to_thread(_llm_plan_question, question)
    except Exception as exc:
        return replace(
            fallback,
            planner_provider="deterministic",
            planner_message=f"LLM question planner failed; deterministic planner used: {exc}",
        )


def classify_question(question: str) -> QuestionComplexity:
    if len(question) > 140 or any(marker in question for marker in ("总结", "概括", "归纳", "整体")):
        return "broad_summary"
    if any(marker in question for marker in ("对比", "区别", "分别", "相比", "影响")):
        return "comparison"
    if len(question) > 80 or any(marker in question for marker in ("并且", "以及", "同时", "多跳", "多个")):
        return "multi_hop"
    return "simple"


def decompose_question(question: str, complexity: QuestionComplexity) -> list[str]:
    if complexity == "simple":
        return [question]
    if complexity == "comparison":
        return [
            f"{question}：先检索对象一的定义、机制和关键事实",
            f"{question}：再检索对象二或对照项的定义、机制和关键事实",
            f"{question}：最后检索两者差异、影响和适用场景",
        ]
    if complexity == "broad_summary":
        return [
            f"{question}：检索核心主题、范围和背景",
            f"{question}：检索关键事实、流程、约束和例外",
            f"{question}：检索结论、风险、建议和可引用来源",
        ]
    return [
        f"{question}：检索第一个子意图的事实和定义",
        f"{question}：检索第二个子意图的流程、约束和影响",
        f"{question}：检索跨子问题的关联、对比和结论",
    ]


def plan_from_llm_content(question: str, content: str) -> QuestionPlan:
    payload = _extract_json_object(content)
    complexity = _normalize_complexity(str(payload.get("complexity", "simple")))
    sub_questions = [
        str(item).strip()
        for item in payload.get("sub_questions", [])
        if str(item).strip()
    ][:4]
    if not sub_questions:
        sub_questions = decompose_question(question, complexity)
    if complexity == "simple":
        sub_questions = [question]

    return QuestionPlan(
        complexity=complexity,
        sub_questions=sub_questions,
        planner_provider="openai-compatible",
        planner_message=f"LLM question planner completed with model {settings.llm_model}.",
    )


def _remote_llm_enabled() -> bool:
    return settings.llm_provider in {"openai", "openai-compatible"} and bool(settings.effective_llm_api_key)


def _llm_plan_question(question: str) -> QuestionPlan:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 RAG 问题规划器。只输出 JSON，不要输出 Markdown。"
                "字段：complexity(simple|multi_hop|comparison|broad_summary), "
                "sub_questions(string array, max 4), reason(string)。"
                "简单事实问题只保留原问题；复杂、多跳、对比和总结问题拆成 2-4 个可独立检索的子问题。"
            ),
        },
        {"role": "user", "content": f"用户问题：{question}"},
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
    return plan_from_llm_content(question, body["choices"][0]["message"]["content"])


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).removesuffix("```").strip()
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM planner did not return a JSON object.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM planner JSON is not an object.")
    return parsed


def _normalize_complexity(value: str) -> QuestionComplexity:
    if value in {"simple", "multi_hop", "comparison", "broad_summary"}:
        return value  # type: ignore[return-value]
    return "simple"
