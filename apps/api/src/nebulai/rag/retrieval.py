import asyncio
from dataclasses import dataclass
from typing import Any

from nebulai.core.config import settings
from nebulai.rag.embeddings import embedding_provider
from nebulai.rag.schemas import RagSource
from nebulai.stores.milvus import milvus_store
from nebulai.stores.postgres import postgres_store


@dataclass(frozen=True)
class RetrievalResult:
    mode: str
    status: str
    sources: list[RagSource]
    message: str


async def retrieve_sources(question: str, limit: int = 3) -> RetrievalResult:
    try:
        sources = await asyncio.to_thread(_hybrid_search, question, limit)
        sources = await enrich_source_titles(sources)
        sources = await expand_source_contexts(sources)
        if sources:
            return RetrievalResult(
                mode="milvus_hybrid",
                status="completed",
                sources=sources,
                message="Milvus Dense + BM25 Sparse hybrid search completed with RRF ranking.",
            )
        return RetrievalResult(
            mode="milvus_hybrid",
            status="warning",
            sources=[],
            message="Milvus hybrid search returned no sources.",
        )
    except Exception as hybrid_exc:
        try:
            sources = await asyncio.to_thread(_dense_search, question, limit)
            sources = await enrich_source_titles(sources)
            sources = await expand_source_contexts(sources)
            if sources:
                return RetrievalResult(
                    mode="milvus_dense_fallback",
                    status="warning",
                    sources=sources,
                    message=f"Milvus hybrid search failed; dense-only fallback completed: {hybrid_exc}",
                )
        except Exception as dense_exc:
            return RetrievalResult(
                mode="retrieval_failed",
                status="warning",
                sources=[],
                message=f"Milvus hybrid and dense fallback failed; no knowledge source is available: {hybrid_exc}; {dense_exc}",
            )

        return RetrievalResult(
            mode="retrieval_failed",
            status="warning",
            sources=[],
            message=f"Milvus hybrid search failed and dense fallback returned no sources; no knowledge source is available: {hybrid_exc}",
        )


async def enrich_source_titles(sources: list[RagSource]) -> list[RagSource]:
    document_ids = sorted({source.documentId for source in sources if source.documentId})
    if not document_ids:
        return sources

    try:
        titles = await postgres_store.get_document_titles(document_ids)
    except Exception:
        return sources

    return apply_document_titles(sources, titles)


def apply_document_titles(sources: list[RagSource], titles: dict[str, str]) -> list[RagSource]:
    return [
        source.model_copy(update={"documentTitle": titles.get(source.documentId, source.documentTitle)})
        if source.documentId
        else source
        for source in sources
    ]


async def expand_source_contexts(sources: list[RagSource]) -> list[RagSource]:
    chunk_ids = sorted(
        {
            chunk_id
            for source in sources
            for chunk_id in (source.chunkId, source.parentId)
            if chunk_id
        }
    )
    if not chunk_ids:
        return sources

    try:
        chunks = await postgres_store.get_chunks_by_ids(chunk_ids)
    except Exception:
        return sources

    l1_ids = _auto_merge_l1_ids(sources, chunks)
    if l1_ids:
        try:
            chunks.update(await postgres_store.get_chunks_by_ids(sorted(l1_ids)))
        except Exception:
            pass

    expanded: list[RagSource] = []
    for source in sources:
        hit_chunk = chunks.get(source.chunkId)
        parent_chunk = chunks.get(source.parentId or "")
        l1_chunk = chunks.get(parent_chunk.parent_id) if parent_chunk is not None and parent_chunk.parent_id else None
        context_chunk = l1_chunk or parent_chunk or hit_chunk
        context = context_chunk.text if context_chunk is not None else source.context
        expanded.append(
            source.model_copy(
                update={
                    "context": context,
                    "contextChunkId": context_chunk.id if context_chunk is not None else source.contextChunkId,
                    "contextLevel": context_chunk.level if context_chunk is not None else source.contextLevel,
                }
            )
        )
    return expanded


def _auto_merge_l1_ids(sources: list[RagSource], chunks: dict[str, Any]) -> set[str]:
    l1_hit_counts: dict[str, int] = {}
    for source in sources:
        parent_chunk = chunks.get(source.parentId or "")
        if parent_chunk is None or not parent_chunk.parent_id:
            continue
        l1_hit_counts[parent_chunk.parent_id] = l1_hit_counts.get(parent_chunk.parent_id, 0) + 1
    return {chunk_id for chunk_id, count in l1_hit_counts.items() if count >= 2}


def _hybrid_search(question: str, limit: int) -> list[RagSource]:
    from pymilvus import AnnSearchRequest, RRFRanker

    client = milvus_store.client()
    if not client.has_collection(milvus_store.collection_name, timeout=settings.milvus_timeout_seconds):
        return []

    dense_request = AnnSearchRequest(
        data=[embedding_provider.embed_text(question)],
        anns_field="dense_vector",
        param={"metric_type": "COSINE"},
        limit=limit,
    )
    sparse_request = AnnSearchRequest(
        data=[question],
        anns_field="sparse_vector",
        param={"metric_type": "BM25"},
        limit=limit,
    )
    results = client.hybrid_search(
        collection_name=milvus_store.collection_name,
        reqs=[dense_request, sparse_request],
        ranker=RRFRanker(),
        limit=limit,
        output_fields=["chunk_id", "document_id", "parent_id", "ordinal", "text"],
        timeout=settings.milvus_timeout_seconds,
    )
    hits = results[0] if results else []
    return [_source_from_hit(hit) for hit in hits]


def _dense_search(question: str, limit: int) -> list[RagSource]:
    client = milvus_store.client()
    if not client.has_collection(milvus_store.collection_name, timeout=settings.milvus_timeout_seconds):
        return []

    results = client.search(
        collection_name=milvus_store.collection_name,
        data=[embedding_provider.embed_text(question)],
        anns_field="dense_vector",
        search_params={"metric_type": "COSINE"},
        limit=limit,
        output_fields=["chunk_id", "document_id", "parent_id", "ordinal", "text"],
        timeout=settings.milvus_timeout_seconds,
    )
    hits = results[0] if results else []
    return [_source_from_hit(hit) for hit in hits]


def _source_from_hit(hit: dict[str, Any]) -> RagSource:
    entity = hit.get("entity") or {}
    document_id = entity.get("document_id", "unknown")
    text = str(entity.get("text", ""))
    parent_id = str(entity.get("parent_id") or "") or None
    return RagSource(
        documentId=str(document_id),
        documentTitle=f"Document {str(document_id)[:8]}",
        chunkId=str(entity.get("chunk_id", hit.get("id", "unknown"))),
        parentId=parent_id,
        excerpt=_source_excerpt(text),
        context=text,
        contextChunkId=str(entity.get("chunk_id", hit.get("id", "unknown"))),
        contextLevel=str(entity.get("level", "L3")),
        score=float(hit.get("distance")) if hit.get("distance") is not None else None,
        rerankScore=None,
    )


def _source_excerpt(text: str, max_chars: int = 320) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}..."
