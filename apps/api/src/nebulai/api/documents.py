from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from nebulai.rag.chunking import IngestedChunk
from nebulai.rag.ingestion import DocumentIngestionResult, ingest_text_document, is_supported_document_file
from nebulai.rag.ingestion_queue import ingestion_queue_runner
from nebulai.stores.milvus import milvus_store
from nebulai.stores.postgres import postgres_store

router = APIRouter(tags=["documents"])


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    status: str
    message: str
    chunk_counts: dict[str, int]


class DocumentStatusResponse(BaseModel):
    id: str
    filename: str
    status: str
    chunk_counts: dict[str, int]
    metadata: dict[str, Any]


class DocumentListResponse(BaseModel):
    documents: list[DocumentStatusResponse]


class DocumentDeleteResponse(BaseModel):
    id: str
    status: str
    vector_status: str
    message: str


class IngestionJobResponse(BaseModel):
    id: str
    document_id: str
    kind: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    error: str | None = None
    payload: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class IngestionJobListResponse(BaseModel):
    jobs: list[IngestionJobResponse]


fallback_documents: dict[str, DocumentStatusResponse] = {}
fallback_chunks: dict[str, list[IngestedChunk]] = {}


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
) -> DocumentUploadResponse:
    raw = await file.read()
    filename = file.filename or "untitled.txt"
    if not is_supported_document_file(filename, file.content_type):
        raise HTTPException(status_code=400, detail="Supported document types are TXT, Markdown, PDF, DOCX, CSV, and XLSX.")

    pg = getattr(request.app.state, "postgres_store", postgres_store)
    queue = getattr(request.app.state, "ingestion_queue_runner", ingestion_queue_runner)
    document_id = str(uuid4())
    metadata: dict[str, Any] = {
        "content_type": file.content_type or "unknown",
        "byte_size": len(raw),
        "chunk_counts": {"L1": 0, "L2": 0, "L3": 0},
        "embedding_status": "pending",
        "vector_status": "pending",
        "ingestion_status": "queued",
        "ingestion_job_status": "queued",
        "ingestion_progress": 0,
    }

    await pg.create_document(document_id, filename, "processing", metadata)
    fallback_documents[document_id] = DocumentStatusResponse(
        id=document_id,
        filename=filename,
        status="processing",
        chunk_counts={"L1": 0, "L2": 0, "L3": 0},
        metadata=metadata,
    )
    if pg.enabled:
        job = await queue.enqueue_document_ingestion(document_id, filename, file.content_type, raw)
        metadata = {
            **metadata,
            "ingestion_job_id": job.id,
            "ingestion_job_status": job.status,
            "ingestion_progress": job.progress,
        }
        fallback_documents[document_id] = fallback_documents[document_id].model_copy(update={"metadata": metadata})
    else:
        fallback_documents[document_id] = fallback_documents[document_id].model_copy(
            update={
                "metadata": {
                    **metadata,
                    "ingestion_job_status": "in_memory_background",
                }
            }
        )
        background_tasks.add_task(_process_document, document_id, filename, file.content_type, raw)

    return DocumentUploadResponse(
        id=document_id,
        filename=filename,
        status="processing",
        message="Document accepted for background ingestion.",
        chunk_counts={"L1": 0, "L2": 0, "L3": 0},
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents() -> DocumentListResponse:
    stored = await postgres_store.list_documents()
    if stored:
        return DocumentListResponse(documents=[_status_from_stored(item) for item in stored])
    return DocumentListResponse(
        documents=sorted(
            fallback_documents.values(),
            key=lambda item: item.id,
            reverse=True,
        )
    )


@router.get("/documents/{document_id}", response_model=DocumentStatusResponse)
async def get_document(document_id: str) -> DocumentStatusResponse:
    stored = await postgres_store.get_document(document_id)
    if stored is not None:
        return _status_from_stored(stored)

    fallback = fallback_documents.get(document_id)
    if fallback is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return fallback


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(document_id: str) -> DocumentDeleteResponse:
    vector_result = await milvus_store.delete_document(document_id)
    await postgres_store.delete_document(document_id)
    fallback_documents.pop(document_id, None)
    fallback_chunks.pop(document_id, None)
    return DocumentDeleteResponse(
        id=document_id,
        status="deleted",
        vector_status=vector_result.status,
        message=vector_result.message,
    )


@router.post("/documents/{document_id}/retry", response_model=DocumentStatusResponse)
async def retry_document(document_id: str, background_tasks: BackgroundTasks) -> DocumentStatusResponse:
    stored = await postgres_store.get_document(document_id)
    fallback = fallback_documents.get(document_id)
    if stored is None:
        if fallback is None:
            raise HTTPException(status_code=404, detail="Document not found.")

    chunks = await postgres_store.get_document_chunks(document_id) if stored is not None else []
    if not chunks:
        chunks = fallback_chunks.get(document_id, [])
    if not chunks:
        raise HTTPException(status_code=400, detail="Document has no persisted chunks to retry.")

    metadata = {
        "ingestion_status": "retrying",
        "embedding_status": "pending",
        "vector_status": "pending",
        "retry_reason": "manual",
        "ingestion_job_status": "queued",
        "ingestion_progress": 0,
    }
    if postgres_store.enabled:
        job = await ingestion_queue_runner.enqueue_vector_retry(document_id)
        metadata = {
            **metadata,
            "ingestion_job_id": job.id,
            "ingestion_job_status": job.status,
            "ingestion_progress": job.progress,
        }
    else:
        background_tasks.add_task(_retry_document_vectors, document_id, chunks)

    await postgres_store.update_document_status(document_id, "processing", metadata)
    if stored is not None:
        queued = _status_from_stored({**stored, "status": "processing", "metadata": {**stored["metadata"], **metadata}})
    else:
        assert fallback is not None
        queued = fallback.model_copy(update={"status": "processing", "metadata": {**fallback.metadata, **metadata}})
    fallback_documents[document_id] = queued
    return queued


@router.get("/documents/{document_id}/jobs", response_model=IngestionJobListResponse)
async def list_document_ingestion_jobs(document_id: str) -> IngestionJobListResponse:
    stored = await postgres_store.get_document(document_id)
    if stored is None and document_id not in fallback_documents:
        raise HTTPException(status_code=404, detail="Document not found.")
    jobs = await postgres_store.list_ingestion_jobs(document_id=document_id)
    return IngestionJobListResponse(jobs=[_job_response(job) for job in jobs])


@router.get("/ingestion/jobs", response_model=IngestionJobListResponse)
async def list_ingestion_jobs() -> IngestionJobListResponse:
    jobs = await postgres_store.list_ingestion_jobs()
    return IngestionJobListResponse(jobs=[_job_response(job) for job in jobs])


def _status_from_result(result: DocumentIngestionResult, metadata: dict[str, Any]) -> DocumentStatusResponse:
    return DocumentStatusResponse(
        id=result.id,
        filename=result.filename,
        status=result.status,
        chunk_counts=result.chunk_counts,
        metadata=metadata,
    )


async def _process_document(document_id: str, filename: str, content_type: str | None, raw: bytes) -> None:
    try:
        result = ingest_text_document(filename, content_type, raw, document_id=document_id)
        index_result = await milvus_store.index_leaf_chunks(result.chunks)
        metadata = {
            "content_type": content_type or "unknown",
            "byte_size": len(raw),
            "char_count": len(result.text),
            "chunk_counts": result.chunk_counts,
            "embedding_status": index_result.embedding_status,
            "embedding_provider": index_result.embedding_provider,
            "embedding_message": index_result.embedding_message,
            "vector_status": index_result.status,
            "vector_collection": index_result.collection,
            "vector_inserted_count": index_result.inserted_count,
            "vector_message": index_result.message,
            "ingestion_status": "completed",
        }
        await postgres_store.replace_document_chunks(document_id, result.chunks)
        await postgres_store.update_document_status(document_id, "completed", metadata)
        fallback_documents[document_id] = _status_from_result(result, metadata)
        fallback_chunks[document_id] = result.chunks
    except Exception as exc:
        metadata = {
            "ingestion_status": "failed",
            "ingestion_error": str(exc),
            "embedding_status": "skipped",
            "vector_status": "skipped",
        }
        await postgres_store.update_document_status(document_id, "failed", metadata)
        existing = fallback_documents.get(document_id)
        if existing is not None:
            fallback_documents[document_id] = existing.model_copy(
                update={
                    "status": "failed",
                    "metadata": {**existing.metadata, **metadata},
                }
            )


async def _retry_document_vectors(document_id: str, chunks: list[IngestedChunk]) -> None:
    try:
        index_result = await milvus_store.index_leaf_chunks(chunks)
        metadata = {
            "embedding_status": index_result.embedding_status,
            "embedding_provider": index_result.embedding_provider,
            "embedding_message": index_result.embedding_message,
            "vector_status": index_result.status,
            "vector_collection": index_result.collection,
            "vector_inserted_count": index_result.inserted_count,
            "vector_message": index_result.message,
            "ingestion_status": "completed",
        }
        await postgres_store.update_document_status(document_id, "completed", metadata)
        stored = await postgres_store.get_document(document_id)
        if stored is not None:
            fallback_documents[document_id] = _status_from_stored(stored)
        elif document_id in fallback_documents:
            existing = fallback_documents[document_id]
            fallback_documents[document_id] = existing.model_copy(
                update={
                    "status": "completed",
                    "metadata": {**existing.metadata, **metadata},
                }
            )
    except Exception as exc:
        metadata = {
            "ingestion_status": "failed",
            "retry_error": str(exc),
            "embedding_status": "skipped",
            "vector_status": "skipped",
        }
        await postgres_store.update_document_status(document_id, "failed", metadata)
        existing = fallback_documents.get(document_id)
        if existing is not None:
            fallback_documents[document_id] = existing.model_copy(
                update={
                    "status": "failed",
                    "metadata": {**existing.metadata, **metadata},
                }
            )


def _status_from_stored(stored: dict[str, Any]) -> DocumentStatusResponse:
    return DocumentStatusResponse(
        id=stored["id"],
        filename=stored["filename"],
        status=stored["status"],
        chunk_counts=stored["chunk_counts"],
        metadata=stored["metadata"],
    )


def _job_response(job: dict[str, Any]) -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job["id"],
        document_id=job["document_id"],
        kind=job["kind"],
        status=job["status"],
        progress=job["progress"],
        attempts=job["attempts"],
        max_attempts=job["max_attempts"],
        error=job["error"],
        payload=job["payload"],
        created_at=_iso(job.get("created_at")),
        updated_at=_iso(job.get("updated_at")),
        started_at=_iso(job.get("started_at")),
        finished_at=_iso(job.get("finished_at")),
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
