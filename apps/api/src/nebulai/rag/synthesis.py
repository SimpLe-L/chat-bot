from dataclasses import dataclass
from typing import Literal

from nebulai.rag.schemas import RagSource


@dataclass(frozen=True)
class SynthesisResult:
    status: Literal["completed", "warning"]
    message: str
    sources: list[RagSource]


def synthesize_sources(sources: list[RagSource], *, max_sources: int = 5) -> SynthesisResult:
    if not sources:
        return SynthesisResult(
            status="warning",
            message="没有可用知识库证据；答案必须说明依据不足，不能伪造来源。",
            sources=[],
        )

    selected = _deduplicate_sources(sources)[:max_sources]
    dropped_count = max(0, len(sources) - len(selected))
    parent_count = sum(1 for source in selected if source.contextChunkId and source.contextChunkId != source.chunkId)
    message = (
        f"已整理 {len(selected)} 条候选证据，按当前排序绑定引用编号；"
        f"父块扩展 {parent_count} 条，去重/截断 {dropped_count} 条。"
    )
    return SynthesisResult(status="completed", message=message, sources=selected)


def _deduplicate_sources(sources: list[RagSource]) -> list[RagSource]:
    selected: list[RagSource] = []
    seen: set[str] = set()
    for source in sources:
        key = _evidence_key(source)
        if key in seen:
            continue
        seen.add(key)
        selected.append(source)
    return selected


def _evidence_key(source: RagSource) -> str:
    return source.contextChunkId or source.chunkId
