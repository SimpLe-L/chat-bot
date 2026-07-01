import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nebulai.main import app
from nebulai.rag.answer import AnswerProvider, build_answer_prompt
from nebulai.rag.chunking import IngestedChunk
from nebulai.rag.corrective import assess_relevance, assessment_from_llm_content, build_step_back_query, merge_sources
from nebulai.rag.graph import run_rag_workflow
from nebulai.rag.memory import build_session_summary, build_session_summary_with_llm
from nebulai.rag.rerank import _remote_rerank, apply_rerank_results
from nebulai.rag.retrieval import _source_from_hit, apply_document_titles, expand_source_contexts, retrieve_sources
from nebulai.rag.schemas import ChatStreamRequest, RagSource


def test_chat_stream_contains_langgraph_rag_step() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream",
            json={
                "message": "验证 LangGraph RAG 节点",
                "options": {"show_steps": True},
            },
        )

    assert response.status_code == 200
    assert "event: accepted" in response.text
    assert "LangGraph RAG" in response.text
    assert "no knowledge source is available" in response.text or "event: source" in response.text


def test_rag_workflow_executes_real_langgraph_nodes() -> None:
    result = asyncio.run(
        run_rag_workflow(
            ChatStreamRequest(
                message="请对比 Hybrid Search 和 Dense Search，并且分别说明 rerank 的影响",
            ),
            session_id="workflow-test-session",
        )
    )

    assert result.graph_state["graph_runtime"] == "langgraph_nodes"
    assert result.graph_state["complexity"] == "complex"
    assert result.graph_state["question_plan"].is_complex is True
    assert len(result.graph_state["question_plan"].sub_questions) >= 2
    assert result.retrieval.mode
    assert result.corrective_retrievals
    assert result.corrective_retrievals[0].agent_id == "sub_agent_1"
    assert result.corrective_retrievals[0].rerank is not None
    assert result.answer_plan.provider in {"mock", "openai-compatible"}


def test_cancel_run_endpoint() -> None:
    with TestClient(app) as client:
        response = client.post("/api/chat/runs/test-run-id/cancel")

    assert response.status_code == 200
    assert response.json() == {"run_id": "test-run-id", "status": "cancelled"}


def test_chat_history_endpoints_return_sessions_and_messages() -> None:
    class FakePostgres:
        async def list_sessions(self, *args, **kwargs):
            assert kwargs.get("workspace_id") == "local-workspace"
            return [
                {
                    "id": "session-1",
                    "title": "测试会话",
                    "updated_at": datetime(2026, 6, 30, tzinfo=UTC),
                    "message_count": 2,
                }
            ]

        async def create_session(self, session_id: str, title: str, *args, **kwargs):
            assert session_id
            assert title == "服务端新会话"
            assert args == ("local-user", "local-workspace")

        async def list_messages(self, session_id: str, *args, **kwargs):
            assert session_id == "session-1"
            assert kwargs.get("workspace_id") == "local-workspace"
            return [
                {
                    "id": "message-1",
                    "role": "user",
                    "content": "你好",
                    "created_at": datetime(2026, 6, 30, tzinfo=UTC),
                }
            ]

        async def list_runs(self, session_id: str, *args, **kwargs):
            assert session_id == "session-1"
            assert kwargs.get("workspace_id") == "local-workspace"
            return [
                {
                    "id": "run-1",
                    "session_id": "session-1",
                    "question": "你好",
                    "status": "completed",
                    "mode": "langgraph_rag",
                    "created_at": datetime(2026, 6, 30, tzinfo=UTC),
                    "finished_at": datetime(2026, 6, 30, tzinfo=UTC),
                }
            ]

        async def get_run_trace(self, run_id: str, *args, **kwargs):
            assert run_id == "run-1"
            assert kwargs.get("workspace_id") == "local-workspace"
            return {
                "run": {
                    "id": "run-1",
                    "session_id": "session-1",
                    "question": "你好",
                    "status": "completed",
                    "mode": "langgraph_rag",
                    "created_at": datetime(2026, 6, 30, tzinfo=UTC),
                    "finished_at": None,
                },
                "steps": [{"kind": "retrieval", "title": "检索"}],
                "sources": [{"chunkId": "chunk-1", "documentTitle": "doc.md"}],
            }

        async def rename_session(self, session_id: str, title: str, *args, **kwargs):
            assert session_id == "session-1"
            assert title == "新标题"
            assert kwargs.get("workspace_id") == "local-workspace"

        async def delete_session(self, session_id: str, *args, **kwargs):
            assert session_id == "session-1"
            assert kwargs.get("workspace_id") == "local-workspace"

    with TestClient(app) as client:
        client.app.state.postgres_store = FakePostgres()
        create_response = client.post("/api/chat/sessions", json={"title": "服务端新会话"})
        sessions_response = client.get("/api/chat/sessions")
        messages_response = client.get("/api/chat/sessions/session-1/messages")
        runs_response = client.get("/api/chat/sessions/session-1/runs")
        trace_response = client.get("/api/chat/runs/run-1/trace")
        rename_response = client.patch("/api/chat/sessions/session-1", json={"title": "新标题"})
        delete_response = client.delete("/api/chat/sessions/session-1")

    assert create_response.status_code == 200
    assert create_response.json()["title"] == "服务端新会话"
    assert sessions_response.status_code == 200
    assert sessions_response.json()["sessions"][0]["title"] == "测试会话"
    assert messages_response.status_code == 200
    assert messages_response.json()["messages"][0]["content"] == "你好"
    assert runs_response.json()["runs"][0]["id"] == "run-1"
    assert trace_response.json()["steps"][0]["kind"] == "retrieval"
    assert trace_response.json()["sources"][0]["chunkId"] == "chunk-1"
    assert rename_response.json() == {"session_id": "session-1", "status": "renamed"}
    assert delete_response.json() == {"session_id": "session-1", "status": "deleted"}


def test_source_from_milvus_hit_keeps_document_id() -> None:
    long_text = "可追溯来源内容" * 80
    source = _source_from_hit(
        {
            "id": "fallback-hit-id",
            "distance": 0.91,
            "entity": {
                "chunk_id": "chunk-1",
                "document_id": "document-123456",
                "parent_id": "parent-1",
                "level": "L3",
                "text": long_text,
            },
        }
    )

    assert source.documentId == "document-123456"
    assert source.documentTitle == "Document document"
    assert source.chunkId == "chunk-1"
    assert source.parentId == "parent-1"
    assert source.context == long_text
    assert len(source.excerpt) < len(long_text)
    assert source.score == 0.91


def test_retrieval_failure_does_not_return_mock_source(monkeypatch) -> None:
    def raise_hybrid(question: str, limit: int):
        raise RuntimeError("hybrid dimension mismatch")

    def raise_dense(question: str, limit: int):
        raise RuntimeError("dense dimension mismatch")

    monkeypatch.setattr("nebulai.rag.retrieval._hybrid_search", raise_hybrid)
    monkeypatch.setattr("nebulai.rag.retrieval._dense_search", raise_dense)

    result = asyncio.run(retrieve_sources("劳动法第三条是什么"))

    assert result.mode == "retrieval_failed"
    assert result.sources == []
    assert "no knowledge source is available" in result.message


def test_expand_source_contexts_uses_parent_chunk(monkeypatch) -> None:
    class FakePostgres:
        async def get_chunks_by_ids(self, chunk_ids: list[str]):
            assert set(chunk_ids) == {"chunk-1", "parent-1"}
            return {
                "chunk-1": IngestedChunk(
                    id="chunk-1",
                    document_id="doc-1",
                    parent_id="parent-1",
                    level="L3",
                    ordinal=1,
                    text="第三条的一小段",
                    metadata={},
                ),
                "parent-1": IngestedChunk(
                    id="parent-1",
                    document_id="doc-1",
                    parent_id="root-1",
                    level="L2",
                    ordinal=1,
                    text="劳动法第三条完整父块上下文，包含就业、报酬、休息休假等完整权利。",
                    metadata={},
                ),
            }

    monkeypatch.setattr("nebulai.rag.retrieval.postgres_store", FakePostgres())

    expanded = asyncio.run(
        expand_source_contexts(
            [
                RagSource(
                    documentId="doc-1",
                    documentTitle="劳动法.pdf",
                    chunkId="chunk-1",
                    parentId="parent-1",
                    excerpt="第三条的一小段",
                )
            ]
        )
    )

    assert expanded[0].contextLevel == "L2"
    assert expanded[0].contextChunkId == "parent-1"
    assert "完整父块上下文" in (expanded[0].context or "")


def test_expand_source_contexts_auto_merges_to_l1_when_multiple_l2_hit(monkeypatch) -> None:
    calls: list[set[str]] = []

    class FakePostgres:
        async def get_chunks_by_ids(self, chunk_ids: list[str]):
            calls.append(set(chunk_ids))
            if "root-1" in chunk_ids:
                return {
                    "root-1": IngestedChunk(
                        id="root-1",
                        document_id="doc-1",
                        parent_id=None,
                        level="L1",
                        ordinal=0,
                        text="劳动合同完整章节，包含订立、权利义务、解除和风险提示。",
                        metadata={},
                    )
                }
            return {
                "chunk-1": IngestedChunk(
                    id="chunk-1",
                    document_id="doc-1",
                    parent_id="parent-1",
                    level="L3",
                    ordinal=1,
                    text="订立条款",
                    metadata={},
                ),
                "chunk-2": IngestedChunk(
                    id="chunk-2",
                    document_id="doc-1",
                    parent_id="parent-2",
                    level="L3",
                    ordinal=2,
                    text="解除条款",
                    metadata={},
                ),
                "parent-1": IngestedChunk(
                    id="parent-1",
                    document_id="doc-1",
                    parent_id="root-1",
                    level="L2",
                    ordinal=1,
                    text="订立父块",
                    metadata={},
                ),
                "parent-2": IngestedChunk(
                    id="parent-2",
                    document_id="doc-1",
                    parent_id="root-1",
                    level="L2",
                    ordinal=2,
                    text="解除父块",
                    metadata={},
                ),
            }

    monkeypatch.setattr("nebulai.rag.retrieval.postgres_store", FakePostgres())

    expanded = asyncio.run(
        expand_source_contexts(
            [
                RagSource(documentId="doc-1", documentTitle="劳动合同.pdf", chunkId="chunk-1", parentId="parent-1", excerpt="订立"),
                RagSource(documentId="doc-1", documentTitle="劳动合同.pdf", chunkId="chunk-2", parentId="parent-2", excerpt="解除"),
            ]
        )
    )

    assert calls[-1] == {"root-1"}
    assert expanded[0].contextLevel == "L1"
    assert expanded[0].contextChunkId == "root-1"
    assert expanded[1].contextChunkId == "root-1"
    assert "完整章节" in (expanded[0].context or "")


def test_apply_document_titles_uses_postgres_filename() -> None:
    sources = [
        RagSource(
            documentId="doc-a",
            documentTitle="Document doc-a",
            chunkId="chunk-a",
            excerpt="命中文档 A",
        ),
        RagSource(
            documentId="doc-b",
            documentTitle="Document doc-b",
            chunkId="chunk-b",
            excerpt="命中文档 B",
        ),
    ]

    enriched = apply_document_titles(sources, {"doc-a": "knowledge.md"})

    assert enriched[0].documentTitle == "knowledge.md"
    assert enriched[1].documentTitle == "Document doc-b"


def test_apply_rerank_results_updates_scores_and_order() -> None:
    sources = [
        RagSource(documentTitle="A", chunkId="chunk-a", excerpt="source a", score=0.2),
        RagSource(documentTitle="B", chunkId="chunk-b", excerpt="source b", score=0.8),
    ]

    reranked = apply_rerank_results(
        sources,
        [
            {"index": 1, "relevance_score": 0.93},
            {"index": 0, "relevance_score": 0.41},
        ],
    )

    assert [source.chunkId for source in reranked] == ["chunk-b", "chunk-a"]
    assert reranked[0].rerankScore == 0.93
    assert reranked[1].rerankScore == 0.41


def test_remote_rerank_uses_generic_rerank_settings(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}
    captured_headers: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results":[{"index":0,"relevance_score":0.88}]}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        import json

        captured_payload.update(json.loads(request.data.decode("utf-8")))
        captured_headers.update(dict(request.header_items()))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_api_key", "sf-key")
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_url", "https://api.siliconflow.cn/v1/rerank")
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_model", "BAAI/bge-reranker-v2-m3")
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_instruction", "Rank private knowledge.")
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_max_chunks_per_doc", 8)
    monkeypatch.setattr("nebulai.rag.rerank.settings.rerank_overlap_tokens", 64)

    sources = [RagSource(documentTitle="A", chunkId="chunk-a", excerpt="source a", score=0.2)]
    reranked = _remote_rerank("query", sources)

    assert captured_payload["model"] == "BAAI/bge-reranker-v2-m3"
    assert captured_payload["instruction"] == "Rank private knowledge."
    assert captured_payload["max_chunks_per_doc"] == 8
    assert captured_payload["overlap_tokens"] == 64
    assert captured_headers["Authorization"] == "Bearer sf-key"
    assert reranked[0].rerankScore == 0.88


def test_corrective_relevance_triggers_step_back_without_sources() -> None:
    assessment = assess_relevance("什么是三级分块？", [])

    assert assessment.needs_rewrite is True
    assert assessment.strategy == "hyde"
    assert assessment.score == 0.0
    assert build_step_back_query("什么是三级分块？") in assessment.rewritten_queries


def test_corrective_relevance_accepts_related_source() -> None:
    assessment = assess_relevance(
        "hybrid search rerank",
        [
            RagSource(
                documentTitle="architecture.md",
                chunkId="chunk-1",
                excerpt="Hybrid search combines dense retrieval and rerank scoring.",
                score=0.3,
            )
        ],
    )

    assert assessment.needs_rewrite is False
    assert assessment.score > 0.18


def test_corrective_relevance_uses_complex_strategy_for_multi_hop_question() -> None:
    assessment = assess_relevance(
        "请对比 Hybrid Search 和 Dense Search，并且分别说明 rerank 的影响",
        [RagSource(documentTitle="x", chunkId="x", excerpt="unrelated", score=0.01)],
    )

    assert assessment.needs_rewrite is True
    assert assessment.strategy == "complex"
    assert len(assessment.rewritten_queries) == 3


def test_merge_sources_deduplicates_by_chunk_id() -> None:
    first = RagSource(documentTitle="A", chunkId="same", excerpt="first")
    duplicate = RagSource(documentTitle="B", chunkId="same", excerpt="duplicate")
    second = RagSource(documentTitle="C", chunkId="other", excerpt="second")

    merged = merge_sources([first], [duplicate, second])

    assert [source.excerpt for source in merged] == ["first", "second"]


def test_llm_corrective_assessment_parses_json_content() -> None:
    assessment = assessment_from_llm_content(
        "复杂问题",
        """
        ```json
        {
          "score": 0.12,
          "needs_rewrite": true,
          "strategy": "complex",
          "reason": "需要拆解",
          "rewritten_queries": ["子问题一", "子问题二"]
        }
        ```
        """,
    )

    assert assessment.grader_provider == "openai-compatible"
    assert assessment.needs_rewrite is True
    assert assessment.strategy == "complex"
    assert assessment.rewritten_queries == ["子问题一", "子问题二"]


def test_llm_corrective_assessment_fills_missing_rewrite_queries() -> None:
    assessment = assessment_from_llm_content(
        "什么是三级分块？",
        '{"score":0.05,"needs_rewrite":true,"strategy":"step_back","reason":"低相关","rewritten_queries":[]}',
    )

    assert assessment.needs_rewrite is True
    assert assessment.strategy == "step_back"
    assert assessment.rewritten_queries == [build_step_back_query("什么是三级分块？")]


def test_build_answer_prompt_includes_sources() -> None:
    prompt = build_answer_prompt(
        "怎么验证 RAG？",
        [
            RagSource(
                documentTitle="knowledge.md",
                chunkId="chunk-1",
                excerpt="需要展示检索来源和过程。",
                context="需要展示检索来源、过程、评分、降级和父块上下文。",
                contextChunkId="parent-1",
                contextLevel="L2",
            )
        ],
    )

    assert "用户问题：怎么验证 RAG？" in prompt
    assert "knowledge.md / chunk-1" in prompt
    assert "expanded=L2 / parent-1" in prompt
    assert "需要展示检索来源、过程、评分、降级和父块上下文。" in prompt
    assert "在句末标注对应编号" in prompt


def test_build_answer_prompt_includes_memory_summary() -> None:
    prompt = build_answer_prompt("继续说明", [], memory_summary="用户之前询问过 Hybrid Search。")

    assert "会话摘要" in prompt
    assert "用户之前询问过 Hybrid Search。" in prompt
    assert "当前知识库依据不足" in prompt


def test_build_session_summary_uses_recent_messages() -> None:
    summary = build_session_summary(
        "既有主题：RAG",
        [
            {"role": "user", "content": "什么是 Hybrid Search？"},
            {"role": "assistant", "content": "Hybrid Search 结合 dense 和 sparse。"},
        ],
    )

    assert "既有摘要" in summary
    assert "user: 什么是 Hybrid Search？" in summary
    assert "assistant: Hybrid Search 结合 dense 和 sparse。" in summary


def test_build_session_summary_with_llm_falls_back_without_provider() -> None:
    summary = asyncio.run(
        build_session_summary_with_llm(
            "既有主题：RAG",
            [
                {"role": "user", "content": "什么是 Hybrid Search？"},
                {"role": "assistant", "content": "Hybrid Search 结合 dense 和 sparse。"},
            ],
        )
    )

    assert "既有摘要" in summary
    assert "Hybrid Search" in summary


def test_mock_answer_provider_streams_tokens() -> None:
    async def collect_tokens() -> list[str]:
        tokens: list[str] = []
        async for event in provider.stream_answer("测试问题", [], "mock_fallback"):
            if event.type == "token" and event.token:
                tokens.append(event.token)
        return tokens

    provider = AnswerProvider(provider="mock", api_key="")
    plan = provider.plan()
    tokens = asyncio.run(collect_tokens())

    assert plan.status == "warning"
    assert "mock answer provider" in "".join(tokens)
    assert "知识库上下文" in "".join(tokens)


def test_remote_answer_failure_falls_back_to_mock() -> None:
    async def collect_events():
        events = []
        async for event in provider.stream_answer("测试问题", [], "mock_fallback"):
            events.append(event)
            if len(events) > 20:
                break
        return events

    provider = AnswerProvider(
        provider="openai-compatible",
        api_key="test-key",
        base_url="http://127.0.0.1:1/v1",
        timeout_seconds=0.01,
    )
    events = asyncio.run(collect_events())

    assert events[0].type == "warning"
    assert "fell back to mock" in (events[0].message or "")
    assert any(event.type == "token" for event in events)
