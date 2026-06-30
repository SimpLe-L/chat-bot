import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol, TypedDict
from uuid import uuid4

from nebulai.rag.answer import AnswerPlan, answer_provider
from nebulai.rag.corrective import RelevanceAssessment, assess_relevance_with_llm, merge_sources
from nebulai.rag.rerank import RerankResult, rerank_sources
from nebulai.rag.retrieval import RetrievalResult, retrieve_sources
from nebulai.rag.schemas import ChatStreamEvent, ChatStreamRequest, RagStep


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_step(
    kind: RagStep.model_fields["kind"].annotation,
    title: str,
    detail: str,
    status: RagStep.model_fields["status"].annotation = "completed",
    score: float | None = None,
) -> RagStep:
    return RagStep(
        kind=kind,
        title=title,
        detail=detail,
        status=status,
        score=score,
        createdAt=now_iso(),
    )


class CancellationChecker(Protocol):
    async def is_cancelled(self, run_id: str) -> bool: ...


class RagGraphState(TypedDict, total=False):
    question: str
    session_id: str
    memory_summary: str | None
    complexity: str
    graph_runtime: str
    retrieval: RetrievalResult
    relevance: RelevanceAssessment
    corrective_retrievals: list["CorrectiveRetrieval"]
    effective_sources_count: int
    rerank: RerankResult
    answer_plan: AnswerPlan


@dataclass(frozen=True)
class CorrectiveRetrieval:
    query: str
    result: RetrievalResult
    agent_id: str = "sub_agent_1"


@dataclass(frozen=True)
class RagWorkflowResult:
    graph_state: RagGraphState
    retrieval: RetrievalResult
    relevance: RelevanceAssessment
    corrective_retrievals: list[CorrectiveRetrieval]
    rerank: RerankResult
    answer_plan: AnswerPlan


@lru_cache(maxsize=1)
def build_langgraph_app() -> Any | None:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return None

    async def analyze_question(state: RagGraphState) -> RagGraphState:
        return _analyze_question_state(state, "langgraph_nodes")

    async def retrieve_context(state: RagGraphState) -> RagGraphState:
        return await _retrieve_context_state(state)

    async def corrective_retrieve(state: RagGraphState) -> RagGraphState:
        return await _corrective_retrieve_state(state)

    async def rerank_context(state: RagGraphState) -> RagGraphState:
        return await _rerank_context_state(state)

    async def plan_answer(state: RagGraphState) -> RagGraphState:
        return _plan_answer_state(state)

    graph = StateGraph(RagGraphState)
    graph.add_node("analyze_question", analyze_question)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("corrective_retrieve", corrective_retrieve)
    graph.add_node("rerank_context", rerank_context)
    graph.add_node("plan_answer", plan_answer)
    graph.add_edge(START, "analyze_question")
    graph.add_edge("analyze_question", "retrieve_context")
    graph.add_edge("retrieve_context", "corrective_retrieve")
    graph.add_edge("corrective_retrieve", "rerank_context")
    graph.add_edge("rerank_context", "plan_answer")
    graph.add_edge("plan_answer", END)
    return graph.compile()


async def run_rag_workflow(
    payload: ChatStreamRequest,
    session_id: str,
    memory_summary: str | None = None,
) -> RagWorkflowResult:
    graph_state: RagGraphState = {
        "question": payload.message,
        "session_id": session_id,
        "memory_summary": memory_summary,
        "graph_runtime": "direct_fallback",
    }
    graph_app = build_langgraph_app()

    if graph_app is not None:
        graph_state = await graph_app.ainvoke(graph_state)
    else:
        graph_state = await _run_direct_workflow(graph_state)

    return RagWorkflowResult(
        graph_state=graph_state,
        retrieval=graph_state["retrieval"],
        relevance=graph_state["relevance"],
        corrective_retrievals=graph_state.get("corrective_retrievals", []),
        rerank=graph_state["rerank"],
        answer_plan=graph_state["answer_plan"],
    )


async def _run_direct_workflow(graph_state: RagGraphState) -> RagGraphState:
    graph_state = _analyze_question_state(graph_state, "direct_fallback")
    graph_state = await _retrieve_context_state(graph_state)
    graph_state = await _corrective_retrieve_state(graph_state)
    graph_state = await _rerank_context_state(graph_state)
    return _plan_answer_state(graph_state)


def _analyze_question_state(graph_state: RagGraphState, runtime: str) -> RagGraphState:
    question = graph_state["question"]
    complexity = "complex" if len(question) > 80 or "并且" in question else "simple"
    return {**graph_state, "complexity": complexity, "graph_runtime": runtime}


async def _retrieve_context_state(graph_state: RagGraphState) -> RagGraphState:
    retrieval = await retrieve_sources(graph_state["question"])
    return {**graph_state, "retrieval": retrieval}


async def _corrective_retrieve_state(graph_state: RagGraphState) -> RagGraphState:
    question = graph_state["question"]
    retrieval = graph_state["retrieval"]
    relevance = await assess_relevance_with_llm(question, retrieval.sources)
    corrective_retrievals = (
        await _run_retrieval_sub_agents(relevance.rewritten_queries)
        if relevance.needs_rewrite
        else []
    )
    return {
        **graph_state,
        "relevance": relevance,
        "corrective_retrievals": corrective_retrievals,
    }


async def _rerank_context_state(graph_state: RagGraphState) -> RagGraphState:
    retrieval = graph_state["retrieval"]
    corrective_retrievals = graph_state.get("corrective_retrievals", [])
    corrective_sources = merge_sources(*[item.result.sources for item in corrective_retrievals])
    effective_sources = merge_sources(corrective_sources, retrieval.sources) if corrective_sources else retrieval.sources
    rerank = await rerank_sources(graph_state["question"], effective_sources)
    return {
        **graph_state,
        "effective_sources_count": len(effective_sources),
        "rerank": rerank,
    }


def _plan_answer_state(graph_state: RagGraphState) -> RagGraphState:
    return {**graph_state, "answer_plan": answer_provider.plan()}


async def _run_retrieval_sub_agents(queries: list[str]) -> list[CorrectiveRetrieval]:
    async def run(index: int, query: str) -> CorrectiveRetrieval:
        return CorrectiveRetrieval(
            query=query,
            result=await retrieve_sources(query),
            agent_id=f"sub_agent_{index + 1}",
        )

    return list(await asyncio.gather(*(run(index, query) for index, query in enumerate(queries))))


async def run_rag_stream(
    payload: ChatStreamRequest,
    run_id: str,
    session_id: str,
    cancellation: CancellationChecker,
    memory_summary: str | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    yield ChatStreamEvent(type="accepted", runId=run_id, sessionId=session_id)
    await asyncio.sleep(0.08)
    workflow = await run_rag_workflow(payload, session_id, memory_summary)
    graph_state = workflow.graph_state
    retrieval = workflow.retrieval
    relevance = workflow.relevance
    rerank = workflow.rerank
    sources = rerank.sources
    answer_plan = workflow.answer_plan

    if payload.options.show_steps:
        steps = [
            make_step(
                "question_analysis",
                "问题分析",
                (
                    f"LangGraph RAG 节点已分析问题复杂度：{graph_state.get('complexity', 'simple')}；"
                    f"runtime：{graph_state.get('graph_runtime', 'unknown')}。"
                    f"{'已注入会话摘要。' if memory_summary else '暂无会话摘要。'}"
                ),
            ),
            make_step(
                "retrieval",
                "混合检索",
                retrieval.message,
                status=retrieval.status,
                score=relevance.score,
            ),
        ]
        if relevance.needs_rewrite:
            steps.append(
                make_step(
                    "rewrite",
                    "纠错重写",
                    (
                        f"{relevance.reason} 策略：{relevance.strategy}；"
                        f"grader：{relevance.grader_provider}；{relevance.grader_message}；"
                        f"重写查询：{' | '.join(relevance.rewritten_queries)}"
                    ),
                    status="warning",
                    score=relevance.score,
                )
            )
            for corrective_retrieval in workflow.corrective_retrievals:
                steps.append(
                    make_step(
                        "retrieval",
                        "二次检索",
                        (
                            f"{corrective_retrieval.agent_id} completed. "
                            f"{corrective_retrieval.result.message} 查询：{corrective_retrieval.query}"
                        ),
                        status=corrective_retrieval.result.status,
                        score=corrective_retrieval.result.sources[0].score
                        if corrective_retrieval.result.sources
                        else None,
                    )
                )
        else:
            steps.append(
                make_step(
                    "rewrite",
                    "纠错判断",
                    f"{relevance.reason} grader：{relevance.grader_provider}；{relevance.grader_message}",
                    status="completed",
                    score=relevance.score,
                )
            )

        steps.extend(
            [
                make_step(
                    "rerank",
                    "精排",
                    rerank.message,
                    status=rerank.status,
                    score=sources[0].rerankScore if sources else None,
                ),
                make_step(
                    "synthesis",
                    "答案合成",
                    f"根据 {len(sources)} 条候选上下文生成可追溯回答。{answer_plan.message}",
                    status=answer_plan.status,
                ),
            ]
        )
        for step in steps:
            if await cancellation.is_cancelled(run_id):
                yield ChatStreamEvent(
                    type="warning",
                    message="回答已被用户中断。",
                    runId=run_id,
                    sessionId=session_id,
                )
                yield ChatStreamEvent(type="done", runId=run_id, sessionId=session_id)
                return
            yield ChatStreamEvent(type="step", step=step, runId=run_id, sessionId=session_id)
            await asyncio.sleep(0.18)

    for source in sources:
        yield ChatStreamEvent(
            type="source",
            source=source,
            runId=run_id,
            sessionId=session_id,
        )
        await asyncio.sleep(0.05)

    async for answer_event in answer_provider.stream_answer(payload.message, sources, retrieval.mode, memory_summary):
        if await cancellation.is_cancelled(run_id):
            yield ChatStreamEvent(
                type="warning",
                message="回答已被用户中断。",
                runId=run_id,
                sessionId=session_id,
            )
            yield ChatStreamEvent(type="done", runId=run_id, sessionId=session_id)
            return
        if answer_event.type == "warning":
            yield ChatStreamEvent(
                type="warning",
                message=answer_event.message,
                runId=run_id,
                sessionId=session_id,
            )
            continue
        yield ChatStreamEvent(type="token", token=answer_event.token, runId=run_id, sessionId=session_id)

    yield ChatStreamEvent(type="done", runId=run_id, sessionId=session_id)


async def run_mock_rag_stream(payload: ChatStreamRequest) -> AsyncIterator[ChatStreamEvent]:
    class NeverCancelled:
        async def is_cancelled(self, run_id: str) -> bool:
            return False

    run_id = str(uuid4())
    session_id = payload.session_id or str(uuid4())
    async for event in run_rag_stream(payload, run_id, session_id, NeverCancelled()):
        yield event
