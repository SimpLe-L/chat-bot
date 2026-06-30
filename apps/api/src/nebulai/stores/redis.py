from typing import Any

from nebulai.core.config import settings


class RunControlStore:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any | None = None
        self._memory_cancelled: set[str] = set()

    async def connect(self) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError:
            return

        try:
            self._client = Redis.from_url(self._redis_url, decode_responses=True)
            await self._client.ping()
        except Exception:
            self._client = None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def register_run(self, run_id: str, session_id: str) -> None:
        if self._client is None:
            self._memory_cancelled.discard(run_id)
            return
        try:
            await self._client.hset(f"run:{run_id}", mapping={"session_id": session_id, "status": "running"})
            await self._client.expire(f"run:{run_id}", 60 * 60)
            await self._client.delete(f"run:{run_id}:cancelled")
        except Exception:
            self._client = None
            self._memory_cancelled.discard(run_id)

    async def cancel_run(self, run_id: str) -> None:
        if self._client is None:
            self._memory_cancelled.add(run_id)
            return
        try:
            await self._client.set(f"run:{run_id}:cancelled", "1", ex=60 * 60)
            await self._client.hset(f"run:{run_id}", "status", "cancelled")
        except Exception:
            self._client = None
            self._memory_cancelled.add(run_id)

    async def is_cancelled(self, run_id: str) -> bool:
        if self._client is None:
            return run_id in self._memory_cancelled
        try:
            return bool(await self._client.exists(f"run:{run_id}:cancelled"))
        except Exception:
            self._client = None
            return run_id in self._memory_cancelled

    async def finish_run(self, run_id: str, status: str) -> None:
        if self._client is None:
            self._memory_cancelled.discard(run_id)
            return
        try:
            await self._client.hset(f"run:{run_id}", "status", status)
            await self._client.delete(f"run:{run_id}:cancelled")
        except Exception:
            self._client = None
        self._memory_cancelled.discard(run_id)


run_control_store = RunControlStore(settings.redis_url)
