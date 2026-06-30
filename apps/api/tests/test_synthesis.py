from nebulai.rag.schemas import RagSource
from nebulai.rag.synthesis import synthesize_sources


def test_synthesis_deduplicates_by_context_chunk_id() -> None:
    sources = [
        RagSource(
            documentTitle="doc-a",
            chunkId="leaf-1",
            contextChunkId="parent-1",
            contextLevel="L2",
            excerpt="第一段",
            context="父块内容",
        ),
        RagSource(
            documentTitle="doc-a",
            chunkId="leaf-2",
            contextChunkId="parent-1",
            contextLevel="L2",
            excerpt="重复父块",
            context="父块内容",
        ),
        RagSource(documentTitle="doc-b", chunkId="leaf-3", excerpt="另一条证据"),
    ]

    result = synthesize_sources(sources)

    assert result.status == "completed"
    assert [source.chunkId for source in result.sources] == ["leaf-1", "leaf-3"]
    assert "去重/截断 1 条" in result.message


def test_synthesis_warns_without_sources() -> None:
    result = synthesize_sources([])

    assert result.status == "warning"
    assert result.sources == []
    assert "不能伪造来源" in result.message


def test_synthesis_limits_sources() -> None:
    sources = [
        RagSource(documentTitle=f"doc-{index}", chunkId=f"chunk-{index}", excerpt="证据")
        for index in range(7)
    ]

    result = synthesize_sources(sources, max_sources=5)

    assert len(result.sources) == 5
    assert "去重/截断 2 条" in result.message
