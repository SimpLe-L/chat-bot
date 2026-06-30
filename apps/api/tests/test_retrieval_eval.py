import asyncio

from nebulai.evals.retrieval_eval import (
    RetrievalEvalCase,
    build_report,
    load_eval_cases,
    report_to_dict,
    run_retrieval_eval,
    score_retrieval_case,
)
from nebulai.rag.schemas import RagSource


def test_score_retrieval_case_calculates_rank_metrics() -> None:
    case = RetrievalEvalCase(
        id="case-1",
        question="劳动者有哪些权利",
        gold_chunk_ids=("chunk-gold",),
    )
    sources = [
        RagSource(documentTitle="A", chunkId="chunk-noise", excerpt="无关内容"),
        RagSource(documentTitle="B", chunkId="chunk-gold", excerpt="劳动者权利"),
    ]

    result = score_retrieval_case(case, sources, k_values=(1, 2))

    assert result.relevant_ranks == (2,)
    assert result.hit_rate_at_k[1] == 0.0
    assert result.hit_rate_at_k[2] == 1.0
    assert result.recall_at_k[2] == 1.0
    assert result.precision_at_k[2] == 0.5
    assert result.mrr == 0.5
    assert 0 < result.ndcg_at_k[2] < 1


def test_run_retrieval_eval_supports_title_and_context_gold() -> None:
    cases = [
        RetrievalEvalCase(
            id="case-title",
            question="什么是 rerank",
            gold_document_titles=("RAG",),
            gold_context_terms=("rerank",),
        )
    ]

    async def fake_retriever(question: str, limit: int):
        assert question == "什么是 rerank"
        assert limit == 3
        return [
            RagSource(
                documentTitle="RAG 知识体系",
                chunkId="chunk-1",
                excerpt="Rerank 是对初召回候选进行二次排序。",
            )
        ]

    report = asyncio.run(run_retrieval_eval(cases, fake_retriever, limit=3, k_values=(1, 3)))

    assert report.case_count == 1
    assert report.aggregate["hit_rate@1"] == 1.0
    assert report.aggregate["recall@1"] == 1.0
    assert report_to_dict(report)["cases"][0]["matched_sources"] == ["RAG 知识体系 | chunk-1"]


def test_load_eval_cases_reads_jsonl(tmp_path) -> None:
    evalset = tmp_path / "evalset.jsonl"
    evalset.write_text(
        '{"id":"case-1","question":"问题","gold_document_ids":["doc-1"],"tags":["smoke"]}\n',
        encoding="utf-8",
    )

    cases = load_eval_cases(evalset)

    assert cases[0].id == "case-1"
    assert cases[0].gold_document_ids == ("doc-1",)
    assert cases[0].tags == ("smoke",)


def test_build_report_averages_metrics() -> None:
    results = [
        score_retrieval_case(
            RetrievalEvalCase(id="hit", question="q", gold_chunk_ids=("gold",)),
            [RagSource(documentTitle="doc", chunkId="gold", excerpt="hit")],
            k_values=(1,),
        ),
        score_retrieval_case(
            RetrievalEvalCase(id="miss", question="q", gold_chunk_ids=("gold",)),
            [RagSource(documentTitle="doc", chunkId="noise", excerpt="miss")],
            k_values=(1,),
        ),
    ]

    report = build_report(results, k_values=(1,))

    assert report.aggregate["hit_rate@1"] == 0.5
    assert report.aggregate["recall@1"] == 0.5
    assert report.aggregate["precision@1"] == 0.5
