from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from nebulai.rag.chunking import IngestedChunk, build_hierarchical_chunks, chunk_counts, normalize_text


TEXT_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "application/markdown",
    "application/octet-stream",
}
PDF_CONTENT_TYPES = {"application/pdf"}
DOCX_CONTENT_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
SUPPORTED_CONTENT_TYPES = TEXT_CONTENT_TYPES | PDF_CONTENT_TYPES | DOCX_CONTENT_TYPES

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}


@dataclass(frozen=True)
class DocumentIngestionResult:
    id: str
    filename: str
    status: str
    message: str
    text: str
    chunks: list[IngestedChunk]
    chunk_counts: dict[str, int]


def ingest_text_document(
    filename: str,
    content_type: str | None,
    raw: bytes,
    document_id: str | None = None,
) -> DocumentIngestionResult:
    safe_filename = filename or "untitled.txt"
    if not is_supported_document_file(safe_filename, content_type):
        raise ValueError("Supported document types are plain text, Markdown, PDF, and DOCX.")

    text = _extract_text(safe_filename, content_type, raw)
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("Document is empty after text normalization.")

    resolved_document_id = document_id or str(uuid4())
    chunks = build_hierarchical_chunks(resolved_document_id, normalized)
    return DocumentIngestionResult(
        id=resolved_document_id,
        filename=safe_filename,
        status="completed",
        message="Document parsed and chunked. Embedding and Milvus indexing are pending P2/P3 follow-up work.",
        text=normalized,
        chunks=chunks,
        chunk_counts=chunk_counts(chunks),
    )


def is_supported_document_file(filename: str, content_type: str | None) -> bool:
    lower_name = filename.lower()
    has_supported_extension = any(lower_name.endswith(extension) for extension in SUPPORTED_EXTENSIONS)
    return has_supported_extension or (content_type or "").split(";")[0].strip().lower() in SUPPORTED_CONTENT_TYPES


def _extract_text(filename: str, content_type: str | None, raw: bytes) -> str:
    lower_name = filename.lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()

    if lower_name.endswith(".pdf") or normalized_content_type in PDF_CONTENT_TYPES:
        return _extract_pdf_text(raw)
    if lower_name.endswith(".docx") or normalized_content_type in DOCX_CONTENT_TYPES:
        return _extract_docx_text(raw)
    return _decode_text(raw)


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Document text encoding is not supported.")


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing requires pypdf; install apps/api[rag] dependencies.") from exc

    reader = PdfReader(BytesIO(raw))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("DOCX file is not a valid Word document.") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise ValueError("DOCX document XML is not valid.") from exc
    paragraphs: list[str] = []

    for paragraph in root.findall(".//w:p", namespace):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{namespace['w']}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{namespace['w']}}}tab":
                parts.append("\t")
            elif node.tag == f"{{{namespace['w']}}}br":
                parts.append("\n")
        paragraph_text = "".join(parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n\n".join(paragraphs)
