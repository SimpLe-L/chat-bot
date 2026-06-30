from typing import Any

from fastapi import APIRouter

from nebulai.rag.provider_status import collect_provider_status

router = APIRouter(tags=["providers"])


@router.get("/providers/status")
async def provider_status(live: bool = False) -> dict[str, Any]:
    return await collect_provider_status(live=live)
