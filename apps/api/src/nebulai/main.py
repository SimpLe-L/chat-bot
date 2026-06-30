from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nebulai.api.chat import router as chat_router
from nebulai.api.documents import router as documents_router
from nebulai.api.health import router as health_router
from nebulai.api.providers import router as providers_router
from nebulai.core.config import settings
from nebulai.rag.ingestion_queue import ingestion_queue_runner
from nebulai.stores.postgres import postgres_store
from nebulai.stores.redis import run_control_store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.testing:
        app.state.postgres_store = postgres_store
        app.state.run_control_store = run_control_store
        app.state.ingestion_queue_runner = ingestion_queue_runner
        yield
        return

    await postgres_store.connect()
    await run_control_store.connect()
    app.state.postgres_store = postgres_store
    app.state.run_control_store = run_control_store
    await ingestion_queue_runner.start()
    app.state.ingestion_queue_runner = ingestion_queue_runner
    try:
        yield
    finally:
        await ingestion_queue_runner.stop()
        await run_control_store.close()
        await postgres_store.close()


def create_app() -> FastAPI:
    app = FastAPI(title="nebulai bot API", version="0.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")

    return app


app = create_app()
