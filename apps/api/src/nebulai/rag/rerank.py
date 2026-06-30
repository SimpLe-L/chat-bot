import asyncio
import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from nebulai.core.config import settings
from nebulai.rag.schemas import RagSource


@dataclass(frozen=True)
class RerankResult:
    status: str
    message: str
    sources: list[RagSource]


async def rerank_sources(question: str, sources: list[RagSource]) -> RerankResult:
    if not sources:
        return RerankResult("warning", "No candidate sources to rerank.", sources)

    provider = settings.effective_rerank_provider
    if not settings.effective_rerank_api_key:
        return RerankResult(
            "warning",
            f"{provider} rerank is not configured; keeping Milvus RRF order.",
            sources,
        )

    try:
        reranked = await asyncio.to_thread(_remote_rerank, question, sources)
        return RerankResult(
            "completed",
            f"{provider} rerank completed and updated source rerank scores.",
            reranked,
        )
    except Exception as exc:
        return RerankResult(
            "warning",
            f"{provider} rerank failed; keeping Milvus RRF order: {exc}",
            sources,
        )


def _remote_rerank(question: str, sources: list[RagSource]) -> list[RagSource]:
    payload: dict[str, Any] = {
        "query": question,
        "top_n": len(sources),
        "documents": [_source_context(source) for source in sources],
        "return_documents": False,
    }
    if settings.effective_rerank_model:
        payload["model"] = settings.effective_rerank_model
    if settings.rerank_instruction:
        payload["instruction"] = settings.rerank_instruction
    if settings.rerank_max_chunks_per_doc is not None:
        payload["max_chunks_per_doc"] = settings.rerank_max_chunks_per_doc
    if settings.rerank_overlap_tokens is not None:
        payload["overlap_tokens"] = settings.rerank_overlap_tokens

    request = urllib.request.Request(
        url=settings.effective_rerank_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.effective_rerank_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.effective_rerank_timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    return apply_rerank_results(sources, body.get("results", []))


def apply_rerank_results(sources: list[RagSource], results: list[dict[str, Any]]) -> list[RagSource]:
    indexed_sources = {index: source for index, source in enumerate(sources)}
    reranked: list[RagSource] = []
    seen: set[int] = set()

    for result in results:
        index = int(result.get("index", -1))
        source = indexed_sources.get(index)
        if source is None:
            continue
        seen.add(index)
        score = result.get("relevance_score", result.get("score"))
        reranked.append(
            source.model_copy(
                update={
                    "rerankScore": float(score) if score is not None else source.rerankScore,
                }
            )
        )

    reranked.extend(source for index, source in indexed_sources.items() if index not in seen)
    return reranked


def _source_context(source: RagSource) -> str:
    return source.context or source.excerpt
