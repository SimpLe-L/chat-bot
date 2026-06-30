from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nebulai.rag.retrieval import retrieve_sources
from nebulai.rag.schemas import RagSource

Retriever = Callable[[str, int], Awaitable[list[RagSource]]]
DEFAULT_EVALSET_PATH = Path(__file__).resolve().parents[3] / "evals" / "rag_evalset.jsonl"


@dataclass(frozen=True)
class RetrievalEvalCase:
    id: str
    question: str
    gold_chunk_ids: tuple[str, ...] = ()
    gold_document_ids: tuple[str, ...] = ()
    gold_document_titles: tuple[str, ...] = ()
    gold_context_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    difficulty: str = "medium"


@dataclass(frozen=True)
class RetrievalCaseResult:
    id: str
    question: str
    retrieved_count: int
    relevant_ranks: tuple[int, ...]
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    hit_rate_at_k: dict[int, float]
    mrr: float
    ndcg_at_k: dict[int, float]
    matched_sources: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalEvalReport:
    case_count: int
    k_values: tuple[int, ...]
    aggregate: dict[str, float]
    cases: tuple[RetrievalCaseResult, ...]


def load_eval_cases(path: Path) -> list[RetrievalEvalCase]:
    cases: list[RetrievalEvalCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        cases.append(eval_case_from_payload(payload, line_number=line_number))
    return cases


def eval_case_from_payload(payload: dict[str, Any], line_number: int | None = None) -> RetrievalEvalCase:
    case_id = str(payload.get("id") or "").strip()
    question = str(payload.get("question") or "").strip()
    if not case_id or not question:
        location = f" line {line_number}" if line_number is not None else ""
        raise ValueError(f"Eval case{location} requires non-empty id and question.")

    return RetrievalEvalCase(
        id=case_id,
        question=question,
        gold_chunk_ids=_tuple_of_strings(payload.get("gold_chunk_ids")),
        gold_document_ids=_tuple_of_strings(payload.get("gold_document_ids")),
        gold_document_titles=_tuple_of_strings(payload.get("gold_document_titles")),
        gold_context_terms=_tuple_of_strings(payload.get("gold_context_terms")),
        tags=_tuple_of_strings(payload.get("tags")),
        difficulty=str(payload.get("difficulty") or "medium"),
    )


async def run_retrieval_eval(
    cases: Sequence[RetrievalEvalCase],
    retriever: Retriever | None = None,
    *,
    limit: int = 5,
    k_values: Sequence[int] = (1, 3, 5),
) -> RetrievalEvalReport:
    resolved_retriever = retriever or _default_retriever
    results: list[RetrievalCaseResult] = []
    for case in cases:
        sources = await resolved_retriever(case.question, limit)
        results.append(score_retrieval_case(case, sources, k_values=k_values))
    return build_report(results, k_values=k_values)


def score_retrieval_case(
    case: RetrievalEvalCase,
    sources: Sequence[RagSource],
    *,
    k_values: Sequence[int] = (1, 3, 5),
) -> RetrievalCaseResult:
    relevant_ranks = tuple(
        index
        for index, source in enumerate(sources, start=1)
        if is_relevant_source(case, source)
    )
    matched_sources = tuple(_source_label(sources[index - 1]) for index in relevant_ranks)
    gold_count = _gold_item_count(case)
    recall_at_k: dict[int, float] = {}
    precision_at_k: dict[int, float] = {}
    hit_rate_at_k: dict[int, float] = {}
    ndcg_at_k: dict[int, float] = {}

    for k in k_values:
        relevant_at_k = sum(1 for rank in relevant_ranks if rank <= k)
        recall_at_k[k] = min(1.0, relevant_at_k / gold_count) if gold_count else float(relevant_at_k > 0)
        precision_at_k[k] = relevant_at_k / k
        hit_rate_at_k[k] = float(relevant_at_k > 0)
        ndcg_at_k[k] = _ndcg_at_k(relevant_ranks, gold_count, k)

    return RetrievalCaseResult(
        id=case.id,
        question=case.question,
        retrieved_count=len(sources),
        relevant_ranks=relevant_ranks,
        recall_at_k=recall_at_k,
        precision_at_k=precision_at_k,
        hit_rate_at_k=hit_rate_at_k,
        mrr=(1 / relevant_ranks[0]) if relevant_ranks else 0.0,
        ndcg_at_k=ndcg_at_k,
        matched_sources=matched_sources,
    )


def build_report(
    results: Sequence[RetrievalCaseResult],
    *,
    k_values: Sequence[int] = (1, 3, 5),
) -> RetrievalEvalReport:
    aggregate: dict[str, float] = {"case_count": float(len(results))}
    if not results:
        return RetrievalEvalReport(0, tuple(k_values), aggregate, ())

    aggregate["mrr"] = _average(result.mrr for result in results)
    for k in k_values:
        aggregate[f"recall@{k}"] = _average(result.recall_at_k[k] for result in results)
        aggregate[f"precision@{k}"] = _average(result.precision_at_k[k] for result in results)
        aggregate[f"hit_rate@{k}"] = _average(result.hit_rate_at_k[k] for result in results)
        aggregate[f"ndcg@{k}"] = _average(result.ndcg_at_k[k] for result in results)

    return RetrievalEvalReport(len(results), tuple(k_values), aggregate, tuple(results))


def report_to_dict(report: RetrievalEvalReport) -> dict[str, Any]:
    return {
        "case_count": report.case_count,
        "k_values": list(report.k_values),
        "aggregate": report.aggregate,
        "cases": [
            {
                "id": result.id,
                "question": result.question,
                "retrieved_count": result.retrieved_count,
                "relevant_ranks": list(result.relevant_ranks),
                "recall_at_k": {str(key): value for key, value in result.recall_at_k.items()},
                "precision_at_k": {str(key): value for key, value in result.precision_at_k.items()},
                "hit_rate_at_k": {str(key): value for key, value in result.hit_rate_at_k.items()},
                "mrr": result.mrr,
                "ndcg_at_k": {str(key): value for key, value in result.ndcg_at_k.items()},
                "matched_sources": list(result.matched_sources),
            }
            for result in report.cases
        ],
    }


def is_relevant_source(case: RetrievalEvalCase, source: RagSource) -> bool:
    chunk_ids = {
        item
        for item in (source.chunkId, source.contextChunkId, source.parentId)
        if item
    }
    if case.gold_chunk_ids and chunk_ids & set(case.gold_chunk_ids):
        return True
    if case.gold_document_ids and source.documentId in set(case.gold_document_ids):
        return True
    if case.gold_document_titles and _matches_any(source.documentTitle, case.gold_document_titles):
        return True
    if case.gold_context_terms:
        context = " ".join(
            part
            for part in (source.documentTitle, source.excerpt, source.context or "")
            if part
        ).lower()
        return all(term.lower() in context for term in case.gold_context_terms)
    return False


async def _default_retriever(question: str, limit: int) -> list[RagSource]:
    result = await retrieve_sources(question, limit=limit)
    return result.sources


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, list):
        raise ValueError(f"Expected string array, got {type(value).__name__}.")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _matches_any(value: str, needles: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(needle.lower() in lowered for needle in needles)


def _gold_item_count(case: RetrievalEvalCase) -> int:
    if case.gold_chunk_ids:
        return len(case.gold_chunk_ids)
    if case.gold_document_ids:
        return len(case.gold_document_ids)
    if case.gold_document_titles:
        return len(case.gold_document_titles)
    if case.gold_context_terms:
        return 1
    return 0


def _ndcg_at_k(relevant_ranks: Sequence[int], gold_count: int, k: int) -> float:
    dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks if rank <= k)
    ideal_relevant = min(gold_count or len(relevant_ranks), k)
    if ideal_relevant <= 0:
        return 0.0
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def _average(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _source_label(source: RagSource) -> str:
    parts = [source.documentTitle, source.chunkId]
    if source.contextChunkId and source.contextChunkId != source.chunkId:
        parts.append(f"context={source.contextChunkId}")
    return " | ".join(parts)


def _parse_k_values(raw: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("k values must be positive integers.")
    return values


async def _main_async(args: argparse.Namespace) -> int:
    cases = load_eval_cases(args.evalset)
    report = await run_retrieval_eval(cases, limit=args.limit, k_values=args.k)
    payload = report_to_dict(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run nebulai retrieval evaluation.")
    parser.add_argument(
        "--evalset",
        type=Path,
        default=DEFAULT_EVALSET_PATH,
        help="Path to JSONL retrieval eval cases.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Retrieval limit per query.")
    parser.add_argument("--k", type=_parse_k_values, default=(1, 3, 5), help="Comma-separated k values.")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
