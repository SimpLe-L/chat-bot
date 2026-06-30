from dataclasses import dataclass
from uuid import uuid5, NAMESPACE_URL


@dataclass(frozen=True)
class IngestedChunk:
    id: str
    document_id: str
    parent_id: str | None
    level: str
    ordinal: int
    text: str
    metadata: dict[str, int | str]


def build_hierarchical_chunks(document_id: str, text: str) -> list[IngestedChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    chunks: list[IngestedChunk] = []
    l1_blocks = _pack_blocks(_split_paragraphs(normalized), max_chars=1800)

    for l1_index, l1_text in enumerate(l1_blocks):
        l1_id = _chunk_id(document_id, "L1", l1_index)
        chunks.append(_chunk(document_id, l1_id, None, "L1", l1_index, l1_text))

        l2_blocks = _pack_blocks(_split_paragraphs(l1_text), max_chars=900)
        for l2_index, l2_text in enumerate(l2_blocks):
            l2_ordinal = len([item for item in chunks if item.level == "L2"])
            l2_id = _chunk_id(document_id, "L2", l2_ordinal)
            chunks.append(_chunk(document_id, l2_id, l1_id, "L2", l2_ordinal, l2_text))

            for l3_text in _leaf_chunks(l2_text, max_chars=420, overlap=80):
                l3_ordinal = len([item for item in chunks if item.level == "L3"])
                l3_id = _chunk_id(document_id, "L3", l3_ordinal)
                chunks.append(_chunk(document_id, l3_id, l2_id, "L3", l3_ordinal, l3_text))

    return chunks


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def chunk_counts(chunks: list[IngestedChunk]) -> dict[str, int]:
    return {
        "L1": sum(1 for chunk in chunks if chunk.level == "L1"),
        "L2": sum(1 for chunk in chunks if chunk.level == "L2"),
        "L3": sum(1 for chunk in chunks if chunk.level == "L3"),
    }


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    return paragraphs or [text.strip()]


def _pack_blocks(parts: list[str], max_chars: int) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    current_size = 0

    for part in parts:
        if len(part) > max_chars:
            if current:
                blocks.append("\n\n".join(current))
                current = []
                current_size = 0
            blocks.extend(_hard_split(part, max_chars=max_chars))
            continue

        next_size = current_size + len(part) + (2 if current else 0)
        if current and next_size > max_chars:
            blocks.append("\n\n".join(current))
            current = [part]
            current_size = len(part)
        else:
            current.append(part)
            current_size = next_size

    if current:
        blocks.append("\n\n".join(current))

    return blocks


def _leaf_chunks(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap)

    return chunks


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[index : index + max_chars].strip() for index in range(0, len(text), max_chars) if text[index : index + max_chars].strip()]


def _chunk(
    document_id: str,
    chunk_id: str,
    parent_id: str | None,
    level: str,
    ordinal: int,
    text: str,
) -> IngestedChunk:
    return IngestedChunk(
        id=chunk_id,
        document_id=document_id,
        parent_id=parent_id,
        level=level,
        ordinal=ordinal,
        text=text,
        metadata={
            "char_count": len(text),
            "source": "text-ingestion-v1",
        },
    )


def _chunk_id(document_id: str, level: str, ordinal: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"nebulai:{document_id}:{level}:{ordinal}"))
