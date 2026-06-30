import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import PurePosixPath
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
CSV_CONTENT_TYPES = {"text/csv", "application/csv"}
XLSX_CONTENT_TYPES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
SUPPORTED_CONTENT_TYPES = TEXT_CONTENT_TYPES | PDF_CONTENT_TYPES | DOCX_CONTENT_TYPES | CSV_CONTENT_TYPES | XLSX_CONTENT_TYPES

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".csv", ".xlsx"}


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
        raise ValueError("Supported document types are TXT, Markdown, PDF, DOCX, CSV, and XLSX.")

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
    if lower_name.endswith(".xlsx") or normalized_content_type in XLSX_CONTENT_TYPES:
        return _extract_xlsx_text(raw)
    if lower_name.endswith(".csv") or normalized_content_type in CSV_CONTENT_TYPES:
        return _extract_csv_text(raw)
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
        return _extract_pdf_text_with_pdfplumber(raw)
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing requires pypdf; install apps/api[rag] dependencies.") from exc

    reader = PdfReader(BytesIO(raw))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[PDF page {index}]\n{text}")
    return "\n\n".join(pages)


def _extract_pdf_text_with_pdfplumber(raw: bytes) -> str:
    import pdfplumber

    blocks: list[str] = []
    with pdfplumber.open(BytesIO(raw)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            page_parts: list[str] = []
            text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
            if text.strip():
                page_parts.append(text.strip())
            tables = page.extract_tables() or []
            for table_index, table in enumerate(tables, start=1):
                table_text = _table_to_text(table)
                if table_text:
                    page_parts.append(f"[table {table_index}]\n{table_text}")
            if page_parts:
                blocks.append(f"[PDF page {page_index}]\n" + "\n\n".join(page_parts))
    return "\n\n".join(blocks)


def _extract_docx_text(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            blocks = _extract_docx_part_blocks(archive, "word/document.xml", "正文")
            for name in sorted(archive.namelist()):
                if _is_docx_supporting_part(name):
                    label = _docx_part_label(name)
                    blocks.extend(_extract_docx_part_blocks(archive, name, label))
    except (BadZipFile, KeyError) as exc:
        raise ValueError("DOCX file is not a valid Word document.") from exc

    return "\n\n".join(block for block in blocks if block.strip())


def _extract_docx_part_blocks(archive: ZipFile, name: str, label: str) -> list[str]:
    document_xml = archive.read(name)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise ValueError("DOCX document XML is not valid.") from exc
    blocks: list[str] = []
    body_node = root.find(".//w:body", namespace)
    body = body_node if body_node is not None else root

    for child in body:
        if child.tag == _w_tag("p"):
            paragraph = _docx_paragraph_text(child)
            if paragraph:
                blocks.append(f"[DOCX {label}]\n{paragraph}")
        elif child.tag == _w_tag("tbl"):
            table = _docx_table_text(child)
            if table:
                blocks.append(f"[DOCX {label} table]\n{table}")

    if not blocks:
        for paragraph in root.findall(".//w:p", namespace):
            paragraph_text = _docx_paragraph_text(paragraph)
            if paragraph_text:
                blocks.append(f"[DOCX {label}]\n{paragraph_text}")
    return blocks


def _docx_paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == _w_tag("t") and node.text:
            parts.append(node.text)
        elif node.tag == _w_tag("tab"):
            parts.append("\t")
        elif node.tag == _w_tag("br"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx_table_text(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall("./w:tr", _DOCX_NS):
        cells = []
        for cell in row.findall("./w:tc", _DOCX_NS):
            cell_text = " ".join(
                text
                for text in (_docx_paragraph_text(paragraph) for paragraph in cell.findall(".//w:p", _DOCX_NS))
                if text
            )
            cells.append(cell_text)
        if any(cells):
            rows.append(cells)
    return _table_to_text(rows)


def _is_docx_supporting_part(name: str) -> bool:
    return name.startswith("word/") and (
        name.startswith("word/header")
        or name.startswith("word/footer")
        or name.startswith("word/footnotes")
        or name.startswith("word/endnotes")
        or name.startswith("word/comments")
    ) and name.endswith(".xml")


def _docx_part_label(name: str) -> str:
    if "/header" in name:
        return "页眉"
    if "/footer" in name:
        return "页脚"
    if "/footnotes" in name:
        return "脚注"
    if "/endnotes" in name:
        return "尾注"
    if "/comments" in name:
        return "批注"
    return PurePosixPath(name).stem


def _w_tag(name: str) -> str:
    return f"{{{_DOCX_NS['w']}}}{name}"


def _extract_csv_text(raw: bytes) -> str:
    text = _decode_text(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(StringIO(text), dialect))
    return "[CSV sheet]\n" + _table_to_text(rows)


def _extract_xlsx_text(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            shared_strings = _xlsx_shared_strings(archive)
            sheets = _xlsx_sheets(archive)
            blocks = []
            for sheet_name, sheet_path in sheets:
                if sheet_path not in archive.namelist():
                    continue
                rows = _xlsx_sheet_rows(archive.read(sheet_path), shared_strings)
                table_text = _table_to_text(rows)
                if table_text:
                    blocks.append(f"[XLSX sheet: {sheet_name}]\n{table_text}")
    except BadZipFile as exc:
        raise ValueError("XLSX file is not a valid Excel workbook.") from exc
    return "\n\n".join(blocks)


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
        strings.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
    return strings


def _xlsx_sheets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = _xlsx_workbook_relationships(archive)
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
        name = str(sheet.attrib.get("name") or "Sheet")
        relationship_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = relationships.get(str(relationship_id), "")
        if not target:
            continue
        path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        sheets.append((name, path))
    return sheets


def _xlsx_workbook_relationships(archive: ZipFile) -> dict[str, str]:
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationships = {}
    for rel in root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        rel_id = str(rel.attrib.get("Id") or "")
        target = str(rel.attrib.get("Target") or "")
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def _xlsx_sheet_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        values: list[str] = []
        for cell in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            values.append(_xlsx_cell_value(cell, shared_strings))
        if any(value.strip() for value in values):
            rows.append(values)
    return rows


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t")).strip()
    value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return value
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def _table_to_text(rows: list[list[str | None]]) -> str:
    cleaned_rows = [[str(cell or "").strip() for cell in row] for row in rows]
    cleaned_rows = [row for row in cleaned_rows if any(row)]
    if not cleaned_rows:
        return ""
    header = cleaned_rows[0]
    body = cleaned_rows[1:] if len(cleaned_rows) > 1 else []
    lines: list[str] = []
    if any(header):
        lines.append("表头：" + " | ".join(_column_label(index, cell) for index, cell in enumerate(header) if cell))
    for row_index, row in enumerate(body, start=2):
        cells = []
        for column_index, cell in enumerate(row):
            if not cell:
                continue
            label = header[column_index] if column_index < len(header) and header[column_index] else _excel_column(column_index)
            cells.append(f"{label}={cell}")
        if cells:
            lines.append(f"第{row_index}行：" + " | ".join(cells))
    if not body:
        lines.extend(" | ".join(cell for cell in row if cell) for row in cleaned_rows)
    return "\n".join(line for line in lines if line)


def _column_label(index: int, value: str) -> str:
    return f"{_excel_column(index)}={value}"


def _excel_column(index: int) -> str:
    result = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
