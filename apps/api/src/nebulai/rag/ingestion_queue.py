import asyncio
from dataclasses import dataclass
from uuid import uuid4

from nebulai.rag.ingestion import ingest_text_document
from nebulai.stores.milvus import milvus_store
from nebulai.stores.postgres import PostgresStore, postgres_store


@dataclass(frozen=True)
class EnqueuedIngestionJob:
    id: str
    document_id: str
    status: str
    progress: int


class IngestionQueueRunner:
    def __init__(self, store: PostgresStore = postgres_store) -> None:
        self._store = store
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._worker_id = f"api-worker-{uuid4()}"

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self._store.enabled or self.running:
            return
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        await self._store.requeue_interrupted_ingestion_jobs()
        self._task = asyncio.create_task(self._run(), name="nebulai-ingestion-queue")
        self.wake()

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        self.wake()
        await self._task
        self._task = None

    def wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    async def enqueue_document_ingestion(
        self,
        document_id: str,
        filename: str,
        content_type: str | None,
        raw: bytes,
    ) -> EnqueuedIngestionJob:
        job_id = str(uuid4())
        await self._store.save_document_blob(document_id, content_type or "unknown", raw)
        await self._store.create_ingestion_job(
            job_id,
            document_id,
            kind="document_ingestion",
            payload={
                "filename": filename,
                "content_type": content_type or "unknown",
                "byte_size": len(raw),
            },
        )
        await self._store.update_document_status(
            document_id,
            "processing",
            {
                "ingestion_job_id": job_id,
                "ingestion_job_status": "queued",
                "ingestion_progress": 0,
            },
        )
        self.wake()
        return EnqueuedIngestionJob(job_id, document_id, "queued", 0)

    async def enqueue_vector_retry(self, document_id: str) -> EnqueuedIngestionJob:
        job_id = str(uuid4())
        await self._store.create_ingestion_job(
            job_id,
            document_id,
            kind="vector_retry",
            payload={"retry_reason": "manual"},
        )
        await self._store.update_document_status(
            document_id,
            "processing",
            {
                "ingestion_job_id": job_id,
                "ingestion_job_status": "queued",
                "ingestion_progress": 0,
                "retry_reason": "manual",
                "embedding_status": "pending",
                "vector_status": "pending",
            },
        )
        self.wake()
        return EnqueuedIngestionJob(job_id, document_id, "queued", 0)

    async def _run(self) -> None:
        assert self._wake_event is not None
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            job = await self._store.claim_next_ingestion_job(self._worker_id)
            if job is None:
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=5.0)
                except TimeoutError:
                    pass
                continue
            await self._process_job(job)

    async def _process_job(self, job: dict) -> None:
        document_id = job["document_id"]
        job_id = job["id"]
        try:
            await self._store.update_ingestion_job(
                job_id,
                status="running",
                progress=15,
                payload={"worker_id": self._worker_id},
            )
            await self._store.update_document_status(
                document_id,
                "processing",
                {
                    "ingestion_job_id": job_id,
                    "ingestion_job_status": "running",
                    "ingestion_progress": 15,
                },
            )

            if job["kind"] == "vector_retry":
                await self._process_vector_retry(job)
            else:
                await self._process_document_ingestion(job)
        except Exception as exc:
            message = str(exc)
            await self._store.update_ingestion_job(job_id, status="failed", progress=100, error=message)
            await self._store.update_document_status(
                document_id,
                "failed",
                {
                    "ingestion_status": "failed",
                    "ingestion_job_status": "failed",
                    "ingestion_progress": 100,
                    "ingestion_error": message,
                    "embedding_status": "skipped",
                    "vector_status": "skipped",
                },
            )

    async def _process_document_ingestion(self, job: dict) -> None:
        document_id = job["document_id"]
        payload = job["payload"]
        filename = str(payload.get("filename") or "untitled.txt")
        blob = await self._store.get_document_blob(document_id)
        if blob is None:
            raise RuntimeError("Document blob is missing; cannot resume ingestion.")

        result = ingest_text_document(
            filename,
            str(blob["content_type"]),
            blob["data"],
            document_id=document_id,
        )
        await self._store.update_ingestion_job(job["id"], progress=45)
        await self._store.update_document_status(
            document_id,
            "processing",
            {
                "ingestion_progress": 45,
                "chunk_counts": result.chunk_counts,
            },
        )
        index_result = await milvus_store.index_leaf_chunks(result.chunks)
        await self._store.replace_document_chunks(document_id, result.chunks)
        metadata = {
            "content_type": str(blob["content_type"]),
            "byte_size": int(blob["byte_size"]),
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
            "ingestion_job_status": "completed",
            "ingestion_progress": 100,
        }
        await self._store.update_document_status(document_id, "completed", metadata)
        await self._store.update_ingestion_job(
            job["id"],
            status="completed",
            progress=100,
            payload={
                "chunk_counts": result.chunk_counts,
                "vector_status": index_result.status,
                "embedding_status": index_result.embedding_status,
            },
        )

    async def _process_vector_retry(self, job: dict) -> None:
        document_id = job["document_id"]
        chunks = await self._store.get_document_chunks(document_id)
        if not chunks:
            raise RuntimeError("Document has no persisted chunks to retry.")
        await self._store.update_ingestion_job(job["id"], progress=45)
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
            "ingestion_job_status": "completed",
            "ingestion_progress": 100,
            "retry_reason": "manual",
        }
        await self._store.update_document_status(document_id, "completed", metadata)
        await self._store.update_ingestion_job(
            job["id"],
            status="completed",
            progress=100,
            payload={
                "vector_status": index_result.status,
                "embedding_status": index_result.embedding_status,
            },
        )


ingestion_queue_runner = IngestionQueueRunner()
