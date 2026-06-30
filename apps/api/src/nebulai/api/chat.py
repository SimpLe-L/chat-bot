from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nebulai.core.sse import encode_sse
from nebulai.rag.graph import run_rag_stream
from nebulai.rag.memory import build_session_summary_with_llm
from nebulai.rag.schemas import ChatStreamRequest
from nebulai.stores.postgres import postgres_store
from nebulai.stores.redis import run_control_store

router = APIRouter(tags=["chat"])


class CancelRunResponse(BaseModel):
    run_id: str
    status: str


class RenameSessionRequest(BaseModel):
    title: str


class ChatSessionMutationResponse(BaseModel):
    session_id: str
    status: str


class CreateSessionRequest(BaseModel):
    title: str = "新的知识库问答"


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    message_count: int


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class ChatSessionsResponse(BaseModel):
    sessions: list[ChatSessionSummary]


class ChatMessagesResponse(BaseModel):
    messages: list[ChatMessageResponse]


class ChatRunSummary(BaseModel):
    id: str
    session_id: str
    question: str
    status: str
    mode: str
    created_at: str
    finished_at: str | None = None


class ChatRunsResponse(BaseModel):
    runs: list[ChatRunSummary]


class ChatRunTraceResponse(BaseModel):
    run: ChatRunSummary
    steps: list[dict]
    sources: list[dict]


@router.get("/chat/sessions", response_model=ChatSessionsResponse)
async def list_chat_sessions(request: Request) -> ChatSessionsResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    sessions = await pg.list_sessions()
    return ChatSessionsResponse(
        sessions=[
            ChatSessionSummary(
                id=session["id"],
                title=session["title"],
                updated_at=session["updated_at"].isoformat(),
                message_count=session["message_count"],
            )
            for session in sessions
        ]
    )


@router.post("/chat/sessions", response_model=ChatSessionSummary)
async def create_chat_session(payload: CreateSessionRequest, request: Request) -> ChatSessionSummary:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    session_id = str(uuid4())
    await pg.create_session(session_id, payload.title)
    from datetime import UTC, datetime

    return ChatSessionSummary(
        id=session_id,
        title=payload.title[:80] or "新的知识库问答",
        updated_at=datetime.now(UTC).isoformat(),
        message_count=0,
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatMessagesResponse)
async def list_chat_messages(session_id: str, request: Request) -> ChatMessagesResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    messages = await pg.list_messages(session_id)
    return ChatMessagesResponse(
        messages=[
            ChatMessageResponse(
                id=message["id"],
                role=message["role"],
                content=message["content"],
                created_at=message["created_at"].isoformat(),
            )
            for message in messages
        ]
    )


@router.get("/chat/sessions/{session_id}/runs", response_model=ChatRunsResponse)
async def list_chat_runs(session_id: str, request: Request) -> ChatRunsResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    runs = await pg.list_runs(session_id)
    return ChatRunsResponse(runs=[_run_summary(run) for run in runs])


@router.get("/chat/runs/{run_id}/trace", response_model=ChatRunTraceResponse)
async def get_chat_run_trace(run_id: str, request: Request) -> ChatRunTraceResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    trace = await pg.get_run_trace(run_id)
    if trace is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Run trace not found.")
    return ChatRunTraceResponse(
        run=_run_summary(trace["run"]),
        steps=trace["steps"],
        sources=trace["sources"],
    )


@router.patch("/chat/sessions/{session_id}", response_model=ChatSessionMutationResponse)
async def rename_chat_session(
    session_id: str,
    payload: RenameSessionRequest,
    request: Request,
) -> ChatSessionMutationResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    await pg.rename_session(session_id, payload.title)
    return ChatSessionMutationResponse(session_id=session_id, status="renamed")


@router.delete("/chat/sessions/{session_id}", response_model=ChatSessionMutationResponse)
async def delete_chat_session(session_id: str, request: Request) -> ChatSessionMutationResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    await pg.delete_session(session_id)
    return ChatSessionMutationResponse(session_id=session_id, status="deleted")


@router.post("/chat/stream")
async def stream_chat(payload: ChatStreamRequest, request: Request) -> StreamingResponse:
    run_id = str(uuid4())
    session_id = payload.session_id or str(uuid4())
    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())
    answer_tokens: list[str] = []

    pg = getattr(request.app.state, "postgres_store", postgres_store)
    control = getattr(request.app.state, "run_control_store", run_control_store)

    async def event_stream():
        final_status = "completed"
        await control.register_run(run_id, session_id)
        await pg.create_session(session_id, payload.message)
        await pg.append_message(user_message_id, session_id, "user", payload.message)
        await pg.create_run(run_id, session_id, payload.message, "langgraph_rag")
        memory_summary = await pg.get_session_summary(session_id)

        try:
            async for event in run_rag_stream(payload, run_id, session_id, control, memory_summary):
                if await request.is_disconnected():
                    final_status = "cancelled"
                    await control.cancel_run(run_id)
                    break

                if event.type == "token" and event.token:
                    answer_tokens.append(event.token)
                if event.type == "warning" and event.message == "回答已被用户中断。":
                    final_status = "cancelled"

                await pg.record_event(event)
                yield encode_sse(event.type, event.model_dump(mode="json"))
        except Exception as exc:
            final_status = "error"
            error_event = {
                "type": "error",
                "runId": run_id,
                "sessionId": session_id,
                "message": f"问答链路异常：{exc}",
                "step": None,
                "source": None,
                "token": None,
            }
            yield encode_sse("error", error_event)
        finally:
            if answer_tokens:
                await pg.append_message(
                    assistant_message_id,
                    session_id,
                    "assistant",
                    "".join(answer_tokens),
                )
                messages = await pg.list_messages(session_id)
                summary = await build_session_summary_with_llm(memory_summary, messages)
                await pg.update_session_summary(session_id, summary)
            await pg.finish_run(run_id, final_status)
            await control.finish_run(run_id, final_status)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/runs/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_chat_run(run_id: str, request: Request) -> CancelRunResponse:
    control = getattr(request.app.state, "run_control_store", run_control_store)
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    await control.cancel_run(run_id)
    await pg.finish_run(run_id, "cancelled")
    return CancelRunResponse(run_id=run_id, status="cancelled")


def _run_summary(run: dict) -> ChatRunSummary:
    finished_at = run.get("finished_at")
    return ChatRunSummary(
        id=run["id"],
        session_id=run["session_id"],
        question=run["question"],
        status=run["status"],
        mode=run["mode"],
        created_at=run["created_at"].isoformat(),
        finished_at=finished_at.isoformat() if finished_at is not None else None,
    )
