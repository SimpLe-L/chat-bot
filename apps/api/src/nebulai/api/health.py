from fastapi import APIRouter

from nebulai.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "nebulai-api",
        "mode": settings.runtime_mode,
    }

