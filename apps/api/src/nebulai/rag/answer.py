import asyncio
import json
import threading
import urllib.request
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from nebulai.core.config import settings
from nebulai.rag.schemas import RagSource


@dataclass(frozen=True)
class AnswerPlan:
    status: Literal["completed", "warning"]
    provider: str
    message: str


@dataclass(frozen=True)
class AnswerEvent:
    type: Literal["token", "warning"]
    token: str | None = None
    message: str | None = None


class AnswerProvider:
    def __init__(
        self,
        provider: str = settings.llm_provider,
        model: str = settings.llm_model,
        base_url: str = settings.llm_base_url,
        api_key: str = settings.effective_llm_api_key,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def remote_enabled(self) -> bool:
        return self.provider in {"openai", "openai-compatible"} and bool(self.api_key)

    def plan(self) -> AnswerPlan:
        if self.remote_enabled:
            return AnswerPlan(
                status="completed",
                provider="openai-compatible",
                message=f"OpenAI-compatible LLM provider is configured; streaming answer tokens with model {self.model}.",
            )
        return AnswerPlan(
            status="warning",
            provider="mock",
            message="LLM provider is not configured; using deterministic mock answer streaming.",
        )

    async def stream_answer(
        self,
        question: str,
        sources: list[RagSource],
        retrieval_mode: str,
        memory_summary: str | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        if self.remote_enabled:
            try:
                async for event in self._stream_remote_answer(question, sources, memory_summary):
                    yield event
                return
            except Exception as exc:
                yield AnswerEvent(
                    type="warning",
                    message=f"LLM provider failed; fell back to mock answer streaming: {exc}",
                )

        for token in build_mock_answer(question, sources, retrieval_mode, memory_summary):
            yield AnswerEvent(type="token", token=token)
            await asyncio.sleep(0.018)

    async def _stream_remote_answer(
        self,
        question: str,
        sources: list[RagSource],
        memory_summary: str | None,
    ) -> AsyncIterator[AnswerEvent]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 nebulai bot 的私有知识库问答助手。只能基于给定来源回答；"
                    "如果来源不足，明确说明依据不足。回答要简洁；"
                    "使用来源信息时必须在对应句子后标注 [1]、[2] 这样的引用编号。"
                ),
            },
            {"role": "user", "content": build_answer_prompt(question, sources, memory_summary)},
        ]
        async for token in _iterate_remote_tokens(
            url=f"{self.base_url}/chat/completions",
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            timeout_seconds=self.timeout_seconds,
        ):
            yield AnswerEvent(type="token", token=token)


def build_answer_prompt(question: str, sources: list[RagSource], memory_summary: str | None = None) -> str:
    if not sources:
        context = "当前没有命中可用知识库上下文。"
    else:
        context = "\n\n".join(
            (
                f"[{index + 1}] {source.documentTitle} / {source.chunkId}"
                f"{_context_label(source)}\n{_source_context(source)}"
            )
            for index, source in enumerate(sources)
        )
    memory = f"会话摘要：\n{memory_summary}\n\n" if memory_summary else ""
    return (
        f"{memory}用户问题：{question}\n\n候选来源：\n{context}\n\n"
        "回答要求：\n"
        "- 只能基于候选来源回答。\n"
        "- 使用某条来源支持结论时，在句末标注对应编号，例如 [1]。\n"
        "- 如果没有候选来源或来源不足，直接说明“当前知识库依据不足”，不要编造答案。\n"
    )


def build_mock_answer(
    question: str,
    sources: list[RagSource],
    retrieval_mode: str,
    memory_summary: str | None = None,
) -> Iterable[str]:
    if not sources:
        answer = (
            f"我已经进入 LangGraph RAG 节点 + {retrieval_mode} 模式。"
            "当前没有命中可用知识库上下文，不能基于私有知识库确认答案；"
            "请先上传或重新索引相关文档，或查看 RAG Trace 中的检索失败原因。"
            "当前未配置真实 LLM provider，因此使用 mock answer provider 保持本地链路可验证。你的问题是："
            f"{question}"
        )
        return answer

    context_summary = "；".join(
        f"[{index + 1}] {_source_context(source)}"
        for index, source in enumerate(sources[:2])
    )
    memory_note = f"已注入会话摘要：{memory_summary[:160]}。" if memory_summary else "当前没有可用会话摘要。"
    answer = (
        f"我已经进入 LangGraph RAG 节点 + {retrieval_mode} 模式。当前链路已完成问题分析、检索、纠错、精排和答案规划，"
        "并通过可配置 answer provider 以 SSE token 返回回答；PostgreSQL 会记录会话、消息、RAG run、步骤与来源，"
        "Redis 会记录运行状态和中断信号。"
        f"{memory_note}"
        f"本次检索上下文摘要：{context_summary}。"
        "当前未配置真实 LLM provider，因此使用 mock answer provider 保持本地链路可验证。你的问题是："
        f"{question}"
    )
    return answer


def _source_context(source: RagSource) -> str:
    return source.context or source.excerpt


def _context_label(source: RagSource) -> str:
    if not source.contextChunkId or source.contextChunkId == source.chunkId:
        return ""
    return f"；expanded={source.contextLevel or 'parent'} / {source.contextChunkId}"


async def _iterate_remote_tokens(
    url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_seconds: float,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[tuple[str, str | Exception | None]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker() -> None:
        try:
            for token in _remote_token_iter(url, api_key, model, messages, timeout_seconds):
                loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        kind, payload = await queue.get()
        if kind == "token":
            yield str(payload)
        elif kind == "error":
            raise payload if isinstance(payload, Exception) else RuntimeError("Unknown LLM streaming error.")
        elif kind == "done":
            break


def _remote_token_iter(
    url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_seconds: float,
) -> Iterable[str]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                break

            chunk = json.loads(data)
            for choice in chunk.get("choices", []):
                content = (choice.get("delta") or {}).get("content")
                if content:
                    yield content


answer_provider = AnswerProvider()
