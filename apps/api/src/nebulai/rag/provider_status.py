import asyncio
import json
import urllib.request
from typing import Any

from nebulai.core.config import settings
from nebulai.rag.embeddings import EmbeddingProvider
from nebulai.rag.rerank import rerank_sources
from nebulai.rag.schemas import RagSource


async def collect_provider_status(live: bool = False) -> dict[str, Any]:
    embedding = await _embedding_status(live)
    llm = await _llm_status(live)
    rerank = await _rerank_status(live)
    overall = "ready"
    if any(item["status"] in {"failed", "missing_key"} for item in (embedding, llm, rerank)):
        overall = "degraded"
    if all(item["status"] in {"mock", "not_configured"} for item in (embedding, llm, rerank)):
        overall = "mock"
    return {
        "overall": overall,
        "live": live,
        "providers": {
            "embedding": embedding,
            "llm": llm,
            "rerank": rerank,
        },
    }


async def _embedding_status(live: bool) -> dict[str, Any]:
    provider = EmbeddingProvider()
    configured = provider.provider in {"openai", "openai-compatible"}
    if not configured:
        return {
            "name": "embedding",
            "provider": provider.provider,
            "configured": False,
            "status": "mock",
            "message": "Embedding provider is mock-hash; real embeddings are not configured.",
        }
    if not provider.api_key:
        return {
            "name": "embedding",
            "provider": provider.provider,
            "configured": False,
            "status": "missing_key",
            "message": "Set EMBEDDING_API_KEY, OPENAI_API_KEY, or SILICONFLOW_API_KEY to verify real embeddings.",
        }
    if not live:
        return {
            "name": "embedding",
            "provider": provider.provider,
            "configured": True,
            "status": "configured",
            "message": "Embedding provider is configured; call with live=true to verify.",
        }
    result = await asyncio.to_thread(provider.embed_documents_with_metadata, ["nebulai provider verification"])
    return {
        "name": "embedding",
        "provider": result.provider,
        "configured": True,
        "status": result.status,
        "message": result.message,
    }


async def _llm_status(live: bool) -> dict[str, Any]:
    configured = settings.llm_provider in {"openai", "openai-compatible"}
    if not configured:
        return {
            "name": "llm",
            "provider": settings.llm_provider,
            "configured": False,
            "status": "mock",
            "message": "LLM provider is mock; real answer streaming is not configured.",
        }
    if not settings.effective_llm_api_key:
        return {
            "name": "llm",
            "provider": settings.llm_provider,
            "configured": False,
            "status": "missing_key",
            "message": "Set LLM_API_KEY, OPENAI_API_KEY, or SILICONFLOW_API_KEY to verify real chat completions.",
        }
    if not live:
        return {
            "name": "llm",
            "provider": settings.llm_provider,
            "configured": True,
            "status": "configured",
            "message": "LLM provider is configured; call with live=true to verify.",
        }
    try:
        await asyncio.to_thread(_verify_llm_once)
        return {
            "name": "llm",
            "provider": settings.llm_provider,
            "configured": True,
            "status": "completed",
            "message": f"LLM provider verified with model {settings.llm_model}.",
        }
    except Exception as exc:
        return {
            "name": "llm",
            "provider": settings.llm_provider,
            "configured": True,
            "status": "failed",
            "message": f"LLM provider verification failed: {exc}",
        }


async def _rerank_status(live: bool) -> dict[str, Any]:
    provider = settings.effective_rerank_provider
    if not settings.effective_rerank_api_key:
        return {
            "name": "rerank",
            "provider": provider,
            "configured": False,
            "status": "not_configured",
            "message": (
                "RERANK_API_KEY, JINA_API_KEY, or SILICONFLOW_API_KEY is optional; "
                "rerank will keep Milvus RRF order when it is missing."
            ),
        }
    if not live:
        return {
            "name": "rerank",
            "provider": provider,
            "configured": True,
            "status": "configured",
            "message": f"{provider} rerank is configured; call with live=true to verify.",
        }
    result = await rerank_sources(
        "nebulai provider verification",
        [RagSource(documentTitle="verification", chunkId="provider-check", excerpt="provider verification context")],
    )
    return {
        "name": "rerank",
        "provider": provider,
        "configured": True,
        "status": result.status,
        "message": result.message,
    }


def _verify_llm_once() -> None:
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": "Return the word ok."},
            {"role": "user", "content": "Provider verification."},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 4,
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
    if not body.get("choices"):
        raise RuntimeError("LLM response did not include choices.")
