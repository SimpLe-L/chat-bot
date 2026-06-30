from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatOptions(BaseModel):
    show_steps: bool = True


class ChatStreamRequest(BaseModel):
    session_id: str | None = Field(default=None)
    message: str = Field(min_length=1, max_length=8000)
    options: ChatOptions = Field(default_factory=ChatOptions)


class RagStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: Literal["question_analysis", "rewrite", "retrieval", "rerank", "synthesis", "fallback"]
    title: str
    detail: str
    status: Literal["pending", "running", "completed", "warning", "error"]
    score: float | None = None
    createdAt: str


class RagSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    documentId: str | None = None
    documentTitle: str
    chunkId: str
    parentId: str | None = None
    excerpt: str
    context: str | None = None
    contextChunkId: str | None = None
    contextLevel: str | None = None
    score: float | None = None
    rerankScore: float | None = None


class ChatStreamEvent(BaseModel):
    type: Literal["accepted", "step", "source", "token", "warning", "error", "done"]
    runId: str | None = None
    sessionId: str | None = None
    step: RagStep | None = None
    source: RagSource | None = None
    token: str | None = None
    message: str | None = None
