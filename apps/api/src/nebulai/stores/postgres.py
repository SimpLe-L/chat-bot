import json
from pathlib import Path
from typing import Any

from nebulai.core.config import settings
from nebulai.rag.chunking import IngestedChunk
from nebulai.rag.schemas import ChatStreamEvent

DEFAULT_USER_ID = "local-user"
DEFAULT_WORKSPACE_ID = "local-workspace"


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any | None = None

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        try:
            import asyncpg
        except ImportError:
            return

        try:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            await self.init_schema()
        except OSError:
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def init_schema(self) -> None:
        if self._pool is None:
            return
        schema_path = Path(__file__).with_name("schema.sql")
        await self._pool.execute(schema_path.read_text(encoding="utf-8"))

    async def create_session(
        self,
        session_id: str,
        title: str,
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO sessions (id, title, user_id, workspace_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
            """,
            session_id,
            title[:80] or "新的知识库问答",
            user_id,
            workspace_id,
        )

    async def append_message(
        self,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO messages (id, session_id, role, content, user_id, workspace_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO NOTHING
            """,
            message_id,
            session_id,
            role,
            content,
            user_id,
            workspace_id,
        )

    async def list_sessions(self, limit: int = 30, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            """
            SELECT
              s.id,
              s.title,
              s.updated_at,
              COALESCE(COUNT(m.id), 0) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            WHERE s.workspace_id = $2
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT $1
            """,
            limit,
            workspace_id,
        )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
            }
            for row in rows
        ]

    async def list_messages(self, session_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE session_id = $1 AND workspace_id = $2
            ORDER BY created_at ASC
            """,
            session_id,
            workspace_id,
        )
        return [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def get_session_summary(self, session_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> str | None:
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT summary FROM sessions WHERE id = $1 AND workspace_id = $2",
            session_id,
            workspace_id,
        )
        return row["summary"] if row is not None else None

    async def update_session_summary(
        self,
        session_id: str,
        summary: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            UPDATE sessions
            SET summary = $2, updated_at = NOW()
            WHERE id = $1 AND workspace_id = $3
            """,
            session_id,
            summary,
            workspace_id,
        )

    async def list_runs(
        self,
        session_id: str,
        limit: int = 20,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            """
            SELECT id, session_id, question, status, mode, created_at, finished_at
            FROM rag_runs
            WHERE session_id = $1 AND workspace_id = $3
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            limit,
            workspace_id,
        )
        return [dict(row) for row in rows]

    async def get_run_trace(self, run_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        run = await self._pool.fetchrow(
            """
            SELECT id, session_id, question, status, mode, created_at, finished_at
            FROM rag_runs
            WHERE id = $1 AND workspace_id = $2
            """,
            run_id,
            workspace_id,
        )
        if run is None:
            return None

        step_rows = await self._pool.fetch(
            "SELECT payload FROM rag_steps WHERE run_id = $1 ORDER BY created_at ASC",
            run_id,
        )
        source_rows = await self._pool.fetch(
            "SELECT payload FROM rag_sources WHERE run_id = $1 ORDER BY created_at ASC",
            run_id,
        )
        return {
            "run": dict(run),
            "steps": [_json_payload(row["payload"]) for row in step_rows],
            "sources": [_json_payload(row["payload"]) for row in source_rows],
        }

    async def rename_session(self, session_id: str, title: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            UPDATE sessions
            SET title = $2, updated_at = NOW()
            WHERE id = $1 AND workspace_id = $3
            """,
            session_id,
            title[:80] or "新的知识库问答",
            workspace_id,
        )

    async def title_default_session_from_first_message(
        self,
        session_id: str,
        title: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            UPDATE sessions
            SET title = $2, updated_at = NOW()
            WHERE id = $1
              AND workspace_id = $3
              AND title = '新的知识库问答'
              AND NOT EXISTS (
                SELECT 1
                FROM messages
                WHERE session_id = $1
                  AND workspace_id = $3
                  AND role = 'user'
              )
            """,
            session_id,
            title[:80] or "新的知识库问答",
            workspace_id,
        )

    async def delete_session(self, session_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> None:
        if self._pool is None:
            return
        await self._pool.execute("DELETE FROM sessions WHERE id = $1 AND workspace_id = $2", session_id, workspace_id)

    async def create_document(
        self,
        document_id: str,
        filename: str,
        status: str,
        metadata: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO documents (id, filename, status, metadata, user_id, workspace_id)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            ON CONFLICT (id) DO UPDATE
              SET filename = EXCLUDED.filename,
                  status = EXCLUDED.status,
                  metadata = EXCLUDED.metadata,
                  user_id = EXCLUDED.user_id,
                  workspace_id = EXCLUDED.workspace_id,
                  updated_at = NOW()
            """,
            document_id,
            filename,
            status,
            json.dumps(metadata, ensure_ascii=False),
            user_id,
            workspace_id,
        )

    async def update_document_status(
        self,
        document_id: str,
        status: str,
        metadata: dict[str, Any],
        workspace_id: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        where = "WHERE id = $1" if workspace_id is None else "WHERE id = $1 AND workspace_id = $4"
        values: list[Any] = [document_id, status, json.dumps(metadata, ensure_ascii=False)]
        if workspace_id is not None:
            values.append(workspace_id)
        await self._pool.execute(
            f"""
            UPDATE documents
            SET status = $2, metadata = metadata || $3::jsonb, updated_at = NOW()
            {where}
            """,
            *values,
        )

    async def save_document_blob(self, document_id: str, content_type: str, raw: bytes) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO document_blobs (document_id, content_type, byte_size, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (document_id) DO UPDATE
              SET content_type = EXCLUDED.content_type,
                  byte_size = EXCLUDED.byte_size,
                  data = EXCLUDED.data,
                  created_at = NOW()
            """,
            document_id,
            content_type or "unknown",
            len(raw),
            raw,
        )

    async def get_document_blob(self, document_id: str) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            """
            SELECT document_id, content_type, byte_size, data, created_at
            FROM document_blobs
            WHERE document_id = $1
            """,
            document_id,
        )
        if row is None:
            return None
        return {
            "document_id": row["document_id"],
            "content_type": row["content_type"],
            "byte_size": row["byte_size"],
            "data": bytes(row["data"]),
            "created_at": row["created_at"],
        }

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: list[IngestedChunk],
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("DELETE FROM chunks WHERE document_id = $1", document_id)
                await connection.executemany(
                    """
                    INSERT INTO chunks (id, document_id, parent_id, level, ordinal, text, metadata, user_id, workspace_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (
                            chunk.id,
                            chunk.document_id,
                            chunk.parent_id,
                            chunk.level,
                            chunk.ordinal,
                            chunk.text,
                            json.dumps(chunk.metadata, ensure_ascii=False),
                            user_id,
                            workspace_id,
                        )
                        for chunk in chunks
                    ],
                )

    async def get_document(self, document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            """
            SELECT
              d.id,
              d.filename,
              d.status,
              d.metadata,
              d.created_at,
              d.updated_at,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L1'), 0) AS l1_count,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L2'), 0) AS l2_count,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L3'), 0) AS l3_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.id = $1 AND d.workspace_id = $2
            GROUP BY d.id
            """,
            document_id,
            workspace_id,
        )
        if row is None:
            return None
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {
            "id": row["id"],
            "filename": row["filename"],
            "status": row["status"],
            "metadata": dict(metadata),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "chunk_counts": {
                "L1": row["l1_count"],
                "L2": row["l2_count"],
                "L3": row["l3_count"],
            },
        }

    async def list_documents(self, limit: int = 50, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            """
            SELECT
              d.id,
              d.filename,
              d.status,
              d.metadata,
              d.created_at,
              d.updated_at,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L1'), 0) AS l1_count,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L2'), 0) AS l2_count,
              COALESCE(COUNT(c.id) FILTER (WHERE c.level = 'L3'), 0) AS l3_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.workspace_id = $2
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            LIMIT $1
            """,
            limit,
            workspace_id,
        )
        documents: list[dict[str, Any]] = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            documents.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "status": row["status"],
                    "metadata": dict(metadata),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "chunk_counts": {
                        "L1": row["l1_count"],
                        "L2": row["l2_count"],
                        "L3": row["l3_count"],
                    },
                }
            )
        return documents

    async def get_document_chunks(
        self,
        document_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[IngestedChunk]:
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            """
            SELECT id, document_id, parent_id, level, ordinal, text, metadata
            FROM chunks
            WHERE document_id = $1 AND workspace_id = $2
            ORDER BY ordinal ASC
            """,
            document_id,
            workspace_id,
        )
        chunks: list[IngestedChunk] = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            chunks.append(
                IngestedChunk(
                    id=row["id"],
                    document_id=row["document_id"],
                    parent_id=row["parent_id"],
                    level=row["level"],
                    ordinal=row["ordinal"],
                    text=row["text"],
                    metadata=dict(metadata),
                )
            )
        return chunks

    async def get_chunks_by_ids(
        self,
        chunk_ids: list[str],
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, IngestedChunk]:
        if self._pool is None or not chunk_ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT id, document_id, parent_id, level, ordinal, text, metadata
            FROM chunks
            WHERE id = ANY($1::text[]) AND workspace_id = $2
            """,
            chunk_ids,
            workspace_id,
        )
        chunks: dict[str, IngestedChunk] = {}
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            chunk = IngestedChunk(
                id=row["id"],
                document_id=row["document_id"],
                parent_id=row["parent_id"],
                level=row["level"],
                ordinal=row["ordinal"],
                text=row["text"],
                metadata=dict(metadata),
            )
            chunks[chunk.id] = chunk
        return chunks

    async def delete_document(self, document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID) -> None:
        if self._pool is None:
            return
        await self._pool.execute("DELETE FROM documents WHERE id = $1 AND workspace_id = $2", document_id, workspace_id)

    async def get_document_titles(
        self,
        document_ids: list[str],
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, str]:
        if self._pool is None or not document_ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT id, filename
            FROM documents
            WHERE id = ANY($1::text[]) AND workspace_id = $2
            """,
            document_ids,
            workspace_id,
        )
        return {row["id"]: row["filename"] for row in rows}

    async def create_ingestion_job(
        self,
        job_id: str,
        document_id: str,
        kind: str = "document_ingestion",
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO ingestion_jobs (id, document_id, kind, status, progress, max_attempts, payload, user_id, workspace_id)
            VALUES ($1, $2, $3, 'queued', 0, $4, $5::jsonb, $6, $7)
            ON CONFLICT (id) DO NOTHING
            """,
            job_id,
            document_id,
            kind,
            max_attempts,
            json.dumps(payload or {}, ensure_ascii=False),
            user_id,
            workspace_id,
        )

    async def requeue_interrupted_ingestion_jobs(self) -> int:
        if self._pool is None:
            return 0
        result = await self._pool.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'queued',
                worker_id = NULL,
                locked_at = NULL,
                updated_at = NOW(),
                payload = payload || '{"recovered_from_interrupted_run": true}'::jsonb
            WHERE status = 'running'
            """
        )
        return int(result.split()[-1])

    async def claim_next_ingestion_job(self, worker_id: str) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT id
                    FROM ingestion_jobs
                    WHERE status = 'queued'
                       OR (status = 'failed' AND attempts < max_attempts)
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if row is None:
                    return None
                claimed = await connection.fetchrow(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'running',
                        progress = GREATEST(progress, 5),
                        attempts = attempts + 1,
                        worker_id = $2,
                        locked_at = NOW(),
                        started_at = COALESCE(started_at, NOW()),
                        updated_at = NOW(),
                        error = NULL
                    WHERE id = $1
                    RETURNING *
                    """,
                    row["id"],
                    worker_id,
                )
        return _job_from_row(claimed) if claimed is not None else None

    async def update_ingestion_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        error: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._pool is None:
            return
        assignments = ["updated_at = NOW()"]
        values: list[Any] = [job_id]
        if status is not None:
            values.append(status)
            assignments.append(f"status = ${len(values)}")
            if status in {"completed", "failed"}:
                assignments.append("finished_at = NOW()")
                assignments.append("locked_at = NULL")
                assignments.append("worker_id = NULL")
        if progress is not None:
            values.append(max(0, min(progress, 100)))
            assignments.append(f"progress = ${len(values)}")
        if error is not None:
            values.append(error)
            assignments.append(f"error = ${len(values)}")
        if payload:
            values.append(json.dumps(payload, ensure_ascii=False))
            assignments.append(f"payload = payload || ${len(values)}::jsonb")

        await self._pool.execute(
            f"UPDATE ingestion_jobs SET {', '.join(assignments)} WHERE id = $1",
            *values,
        )

    async def get_ingestion_job(self, job_id: str) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        row = await self._pool.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job_id)
        return _job_from_row(row) if row is not None else None

    async def list_ingestion_jobs(
        self,
        document_id: str | None = None,
        limit: int = 50,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        if document_id:
            rows = await self._pool.fetch(
                """
                SELECT *
                FROM ingestion_jobs
                WHERE document_id = $1 AND workspace_id = $3
                ORDER BY created_at DESC
                LIMIT $2
                """,
                document_id,
                limit,
                workspace_id,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT *
                FROM ingestion_jobs
                WHERE workspace_id = $2
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
                workspace_id,
            )
        return [_job_from_row(row) for row in rows]

    async def create_run(
        self,
        run_id: str,
        session_id: str,
        question: str,
        mode: str,
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO rag_runs (id, session_id, question, mode, user_id, workspace_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO NOTHING
            """,
            run_id,
            session_id,
            question,
            mode,
            user_id,
            workspace_id,
        )

    async def finish_run(self, run_id: str, status: str, workspace_id: str | None = None) -> None:
        if self._pool is None:
            return
        where = "WHERE id = $1" if workspace_id is None else "WHERE id = $1 AND workspace_id = $3"
        values: list[Any] = [run_id, status]
        if workspace_id is not None:
            values.append(workspace_id)
        await self._pool.execute(
            f"UPDATE rag_runs SET status = $2, finished_at = NOW() {where}",
            *values,
        )

    async def record_event(
        self,
        event: ChatStreamEvent,
        user_id: str = DEFAULT_USER_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        if self._pool is None or event.runId is None:
            return

        if event.type == "step" and event.step is not None:
            step = event.step
            await self._pool.execute(
                """
                INSERT INTO rag_steps (id, run_id, kind, title, detail, status, score, payload, user_id, workspace_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                step.id,
                event.runId,
                step.kind,
                step.title,
                step.detail,
                step.status,
                step.score,
                json.dumps(step.model_dump(mode="json"), ensure_ascii=False),
                user_id,
                workspace_id,
            )
            return

        if event.type == "source" and event.source is not None:
            source = event.source
            await self._pool.execute(
                """
                INSERT INTO rag_sources (
                  id, run_id, document_title, chunk_id, excerpt, score, rerank_score, payload, user_id, workspace_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                source.id,
                event.runId,
                source.documentTitle,
                source.chunkId,
                source.excerpt,
                source.score,
                source.rerankScore,
                json.dumps(source.model_dump(mode="json"), ensure_ascii=False),
                user_id,
                workspace_id,
            )

    async def upsert_user(
        self,
        user_id: str,
        email: str | None,
        name: str,
        avatar_url: str | None,
        provider: str,
        provider_subject: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO users (id, email, name, avatar_url, provider, provider_subject)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE
              SET email = EXCLUDED.email,
                  name = EXCLUDED.name,
                  avatar_url = EXCLUDED.avatar_url,
                  provider = EXCLUDED.provider,
                  provider_subject = EXCLUDED.provider_subject,
                  updated_at = NOW()
            """,
            user_id,
            email,
            name,
            avatar_url,
            provider,
            provider_subject,
        )

    async def ensure_personal_workspace(self, user_id: str, name: str) -> str:
        workspace_id = f"workspace-{user_id}"
        if self._pool is None:
            return workspace_id
        await self._pool.execute(
            """
            INSERT INTO workspaces (id, name, owner_user_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
            """,
            workspace_id,
            f"{name} 的知识库",
            user_id,
        )
        await self._pool.execute(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner')
            ON CONFLICT (workspace_id, user_id) DO NOTHING
            """,
            workspace_id,
            user_id,
        )
        return workspace_id

    async def get_user_with_default_workspace(self, user_id: str) -> dict[str, Any] | None:
        if self._pool is None:
            if user_id == DEFAULT_USER_ID:
                return {
                    "id": DEFAULT_USER_ID,
                    "email": "local@nebulai.dev",
                    "name": "Local User",
                    "avatar_url": None,
                    "workspace_id": DEFAULT_WORKSPACE_ID,
                }
            return None
        row = await self._pool.fetchrow(
            """
            SELECT u.id, u.email, u.name, u.avatar_url, wm.workspace_id
            FROM users u
            JOIN workspace_members wm ON wm.user_id = u.id
            WHERE u.id = $1
            ORDER BY wm.created_at ASC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row is not None else None

    async def create_email_code(self, code_id: str, email: str, code_hash: str, expires_minutes: int = 10) -> None:
        if self._pool is None:
            return
        await self._pool.execute(
            """
            INSERT INTO auth_email_codes (id, email, code_hash, expires_at)
            VALUES ($1, $2, $3, NOW() + ($4::int * INTERVAL '1 minute'))
            """,
            code_id,
            email.lower(),
            code_hash,
            expires_minutes,
        )

    async def consume_email_code(self, email: str, code_hash: str) -> bool:
        if self._pool is None:
            return False
        row = await self._pool.fetchrow(
            """
            UPDATE auth_email_codes
            SET consumed_at = NOW()
            WHERE id = (
              SELECT id
              FROM auth_email_codes
              WHERE email = $1
                AND code_hash = $2
                AND consumed_at IS NULL
                AND expires_at > NOW()
              ORDER BY created_at DESC
              LIMIT 1
            )
            RETURNING id
            """,
            email.lower(),
            code_hash,
        )
        return row is not None


postgres_store = PostgresStore(settings.postgres_dsn)


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _job_from_row(row: Any) -> dict[str, Any]:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "kind": row["kind"],
        "status": row["status"],
        "progress": row["progress"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "worker_id": row["worker_id"],
        "user_id": row["user_id"],
        "workspace_id": row["workspace_id"],
        "error": row["error"],
        "payload": dict(payload),
        "locked_at": row["locked_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
