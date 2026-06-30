import asyncio
import operator
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Protocol, TypedDict
from uuid import uuid4

from nebulai.rag.answer import AnswerPlan, answer_provider
from nebulai.rag.corrective import RelevanceAssessment, assess_relevance_with_llm, merge_sources
from nebulai.rag.planning import QuestionPlan, plan_question_with_llm
from nebulai.rag.rerank import RerankResult, rerank_sources
from nebulai.rag.retrieval import RetrievalResult, retrieve_sources
from nebulai.rag.schemas import ChatStreamEvent, ChatStreamRequest, RagStep
from nebulai.rag.synthesis import SynthesisResult, synthesize_sources


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
    run_id: str
    memory_summary: str | None
    event_queue: asyncio.Queue[ChatStreamEvent] | None
    complexity: str
    graph_runtime: str
    question_plan: QuestionPlan
    retrieval: RetrievalResult
    relevance: RelevanceAssessment
    corrective_retrievals: Annotated[list["CorrectiveRetrieval"], operator.add]
    sub_agent_query: str
    sub_agent_index: int
    effective_sources_count: int
    rerank: RerankResult
    synthesis: SynthesisResult
    answer_plan: AnswerPlan


@dataclass(frozen=True)
class CorrectiveRetrieval:
    query: str
    result: RetrievalResult
    agent_id: str = "sub_agent_1"
    relevance: RelevanceAssessment | None = None
    rerank: RerankResult | None = None


@dataclass(frozen=True)
class RagWorkflowResult:
    graph_state: RagGraphState
    retrieval: RetrievalResult
    relevance: RelevanceAssessment
    corrective_retrievals: list[CorrectiveRetrieval]
    rerank: RerankResult
    synthesis: SynthesisResult
    answer_plan: AnswerPlan


@lru_cache(maxsize=1)
def build_langgraph_app() -> Any | None:
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Send
    except ImportError:
        return None

    async def analyze_question(state: RagGraphState) -> RagGraphState:
        return await _analyze_question_state(state, "langgraph_nodes")

    async def retrieve_context(state: RagGraphState) -> RagGraphState:
        return await _retrieve_context_state(state)

    async def corrective_retrieve(state: RagGraphState) -> RagGraphState:
        return await _corrective_retrieve_state(state)

    async def sub_agent_retrieve(state: RagGraphState) -> RagGraphState:
        corrective_retrieval = await _run_single_retrieval_sub_agent(
            state.get("sub_agent_index", 0),
            state["sub_agent_query"],
            event_queue=state.get("event_queue"),
            run_id=state.get("run_id"),
            session_id=state.get("session_id"),
        )
        return {"corrective_retrievals": [corrective_retrieval]}

    async def rerank_context(state: RagGraphState) -> RagGraphState:
        return await _rerank_context_state(state)

    async def plan_answer(state: RagGraphState) -> RagGraphState:
        return await _plan_answer_state(state)

    def route_sub_agents(state: RagGraphState) -> list[Any] | str:
        queries = _sub_agent_queries(state["question_plan"], state["relevance"])
        if not queries:
            return "rerank_context"
        return [
            Send(
                "sub_agent_retrieve",
                {
                    **state,
                    "sub_agent_query": query,
                    "sub_agent_index": index,
                    "corrective_retrievals": [],
                },
            )
            for index, query in enumerate(queries)
        ]

    graph = StateGraph(RagGraphState)
    graph.add_node("analyze_question", analyze_question)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("corrective_retrieve", corrective_retrieve)
    graph.add_node("sub_agent_retrieve", sub_agent_retrieve)
    graph.add_node("rerank_context", rerank_context)
    graph.add_node("plan_answer", plan_answer)
    graph.add_edge(START, "analyze_question")
    graph.add_edge("analyze_question", "retrieve_context")
    graph.add_edge("retrieve_context", "corrective_retrieve")
    graph.add_conditional_edges("corrective_retrieve", route_sub_agents)
    graph.add_edge("sub_agent_retrieve", "rerank_context")
    graph.add_edge("rerank_context", "plan_answer")
    graph.add_edge("plan_answer", END)
    return graph.compile()


async def run_rag_workflow(
    payload: ChatStreamRequest,
    session_id: str,
    memory_summary: str | None = None,
    run_id: str | None = None,
    event_queue: asyncio.Queue[ChatStreamEvent] | None = None,
) -> RagWorkflowResult:
    graph_state: RagGraphState = {
        "question": payload.message,
        "session_id": session_id,
        "run_id": run_id or str(uuid4()),
        "memory_summary": memory_summary,
        "event_queue": event_queue,
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
        synthesis=graph_state["synthesis"],
        answer_plan=graph_state["answer_plan"],
    )


async def _run_direct_workflow(graph_state: RagGraphState) -> RagGraphState:
    graph_state = await _analyze_question_state(graph_state, "direct_fallback")
    graph_state = await _retrieve_context_state(graph_state)
    graph_state = await _corrective_retrieve_state(graph_state)
    graph_state = await _direct_sub_agent_state(graph_state)
    graph_state = await _rerank_context_state(graph_state)
    return await _plan_answer_state(graph_state)


async def _analyze_question_state(graph_state: RagGraphState, runtime: str) -> RagGraphState:
    question_plan = await plan_question_with_llm(graph_state["question"])
    complexity = "simple" if question_plan.complexity == "simple" else "complex"
    next_state: RagGraphState = {
        **graph_state,
        "complexity": complexity,
        "question_plan": question_plan,
        "graph_runtime": runtime,
    }
    await _emit_step(
        next_state,
        make_step(
            "question_analysis",
            "问题分析",
            (
                f"LangGraph RAG 节点已分析问题复杂度：{complexity}；"
                f"runtime：{runtime}。"
                f"planner：{question_plan.planner_provider}；"
                f"子问题数：{len(question_plan.sub_questions)}。"
                f"{'已注入会话摘要。' if graph_state.get('memory_summary') else '暂无会话摘要。'}"
            ),
        ),
    )
    return next_state


async def _retrieve_context_state(graph_state: RagGraphState) -> RagGraphState:
    retrieval = await retrieve_sources(graph_state["question"])
    next_state: RagGraphState = {**graph_state, "retrieval": retrieval}
    await _emit_step(
        next_state,
        make_step(
            "retrieval",
            "混合检索",
            retrieval.message,
            status=retrieval.status,
        ),
    )
    return next_state


async def _corrective_retrieve_state(graph_state: RagGraphState) -> RagGraphState:
    question = graph_state["question"]
    retrieval = graph_state["retrieval"]
    relevance = await assess_relevance_with_llm(question, retrieval.sources)
    await _emit_corrective_steps(graph_state, relevance)
    return {
        **graph_state,
        "relevance": relevance,
        "corrective_retrievals": [],
    }


async def _rerank_context_state(graph_state: RagGraphState) -> RagGraphState:
    retrieval = graph_state["retrieval"]
    corrective_retrievals = graph_state.get("corrective_retrievals", [])
    corrective_sources = merge_sources(*[item.result.sources for item in corrective_retrievals])
    effective_sources = merge_sources(corrective_sources, retrieval.sources) if corrective_sources else retrieval.sources
    rerank = await rerank_sources(graph_state["question"], effective_sources)
    next_state: RagGraphState = {
        **graph_state,
        "effective_sources_count": len(effective_sources),
        "rerank": rerank,
    }
    await _emit_step(
        next_state,
        make_step(
            "rerank",
            "精排",
            rerank.message,
            status=rerank.status,
            score=rerank.sources[0].rerankScore if rerank.sources else None,
        ),
    )
    return next_state


async def _plan_answer_state(graph_state: RagGraphState) -> RagGraphState:
    synthesis = synthesize_sources(graph_state["rerank"].sources)
    answer_plan = answer_provider.plan()
    next_state: RagGraphState = {
        **graph_state,
        "synthesis": synthesis,
        "answer_plan": answer_plan,
    }
    await _emit_step(
        next_state,
        make_step(
            "synthesis",
            "答案合成",
            f"{synthesis.message} {answer_plan.message}",
            status="warning" if synthesis.status == "warning" else answer_plan.status,
        ),
    )
    return next_state


async def _run_retrieval_sub_agents(
    queries: list[str],
    *,
    event_queue: asyncio.Queue[ChatStreamEvent] | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
) -> list[CorrectiveRetrieval]:
    return list(
        await asyncio.gather(
            *(
                _run_single_retrieval_sub_agent(
                    index,
                    query,
                    event_queue=event_queue,
                    run_id=run_id,
                    session_id=session_id,
                )
                for index, query in enumerate(queries)
            )
        )
    )


async def _run_single_retrieval_sub_agent(
    index: int,
    query: str,
    *,
    event_queue: asyncio.Queue[ChatStreamEvent] | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
) -> CorrectiveRetrieval:
    retrieval = await retrieve_sources(query)
    relevance = await assess_relevance_with_llm(query, retrieval.sources)
    secondary_retrievals = (
        await asyncio.gather(*(retrieve_sources(rewrite) for rewrite in relevance.rewritten_queries))
        if relevance.needs_rewrite
        else []
    )
    secondary_sources = merge_sources(*[item.sources for item in secondary_retrievals])
    effective_sources = merge_sources(retrieval.sources, secondary_sources) if secondary_sources else retrieval.sources
    rerank = await rerank_sources(query, effective_sources)
    result = RetrievalResult(
        mode=f"sub_agent:{retrieval.mode}",
        status=rerank.status if rerank.sources else retrieval.status,
        sources=rerank.sources,
        message=(
            f"Sub-agent full retrieval completed. {retrieval.message} "
            f"{relevance.reason} {rerank.message}"
        ),
    )
    corrective_retrieval = CorrectiveRetrieval(
        query=query,
        agent_id=f"sub_agent_{index + 1}",
        result=result,
        relevance=relevance,
        rerank=rerank,
    )
    if event_queue is not None:
        await event_queue.put(
            ChatStreamEvent(
                type="step",
                step=make_step(
                    "retrieval",
                    "Sub-Agent 检索",
                    (
                        f"{corrective_retrieval.agent_id} completed full sub-agent chain. "
                        f"{corrective_retrieval.result.message} 查询：{corrective_retrieval.query}"
                    ),
                    status=corrective_retrieval.result.status,
                    score=corrective_retrieval.result.sources[0].score
                    if corrective_retrieval.result.sources
                    else None,
                ),
                runId=run_id,
                sessionId=session_id,
            )
        )
    return corrective_retrieval


async def _direct_sub_agent_state(graph_state: RagGraphState) -> RagGraphState:
    corrective_retrievals = await _run_retrieval_sub_agents(
        _sub_agent_queries(graph_state["question_plan"], graph_state["relevance"]),
        event_queue=graph_state.get("event_queue"),
        run_id=graph_state.get("run_id"),
        session_id=graph_state.get("session_id"),
    )
    return {**graph_state, "corrective_retrievals": corrective_retrievals}


def _sub_agent_queries(question_plan: QuestionPlan, relevance: RelevanceAssessment) -> list[str]:
    if question_plan.is_complex:
        return question_plan.sub_questions
    if relevance.needs_rewrite:
        return relevance.rewritten_queries
    return []


async def _emit_corrective_steps(graph_state: RagGraphState, relevance: RelevanceAssessment) -> None:
    if relevance.needs_rewrite:
        await _emit_step(
            graph_state,
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
            ),
        )
    else:
        await _emit_step(
            graph_state,
            make_step(
                "rewrite",
                "纠错判断",
                f"{relevance.reason} grader：{relevance.grader_provider}；{relevance.grader_message}",
                status="completed",
                score=relevance.score,
            ),
        )

    question_plan = graph_state["question_plan"]
    if question_plan.is_complex:
        await _emit_step(
            graph_state,
            make_step(
                "rewrite",
                "问题拆解",
                (
                    f"{question_plan.planner_message} "
                    f"复杂度：{question_plan.complexity}；"
                    f"子问题：{' | '.join(question_plan.sub_questions)}"
                ),
                status="completed",
            ),
        )


async def _emit_step(graph_state: RagGraphState, step: RagStep) -> None:
    event_queue = graph_state.get("event_queue")
    if event_queue is None:
        return
    await event_queue.put(
        ChatStreamEvent(
            type="step",
            step=step,
            runId=graph_state.get("run_id"),
            sessionId=graph_state.get("session_id"),
        )
    )


async def run_rag_stream(
    payload: ChatStreamRequest,
    run_id: str,
    session_id: str,
    cancellation: CancellationChecker,
    memory_summary: str | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    yield ChatStreamEvent(type="accepted", runId=run_id, sessionId=session_id)
    await asyncio.sleep(0.08)
    event_queue: asyncio.Queue[ChatStreamEvent] | None = asyncio.Queue() if payload.options.show_steps else None
    workflow_task = asyncio.create_task(
        run_rag_workflow(
            payload,
            session_id,
            memory_summary,
            run_id=run_id,
            event_queue=event_queue,
        )
    )

    if event_queue is not None:
        while not workflow_task.done() or not event_queue.empty():
            if await cancellation.is_cancelled(run_id):
                workflow_task.cancel()
                yield ChatStreamEvent(
                    type="warning",
                    message="回答已被用户中断。",
                    runId=run_id,
                    sessionId=session_id,
                )
                yield ChatStreamEvent(type="done", runId=run_id, sessionId=session_id)
                return
            try:
                yield await asyncio.wait_for(event_queue.get(), timeout=0.05)
            except TimeoutError:
                continue

    workflow = await workflow_task
    retrieval = workflow.retrieval
    synthesis = workflow.synthesis
    sources = synthesis.sources

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
