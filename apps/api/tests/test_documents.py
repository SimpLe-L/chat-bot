from io import BytesIO
from types import SimpleNamespace
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pytest import approx

from nebulai.main import app
from nebulai.rag.chunking import build_hierarchical_chunks, chunk_counts
from nebulai.rag.embeddings import EmbeddingProvider
from nebulai.rag.ingestion import ingest_text_document
from nebulai.stores.milvus import MilvusStore, _collection_dense_vector_dim


def test_chunking_builds_three_level_tree() -> None:
    text = "\n\n".join(
        [
            "第一段用于验证层级分块。",
            "第二段包含更多知识库内容，确保 leaf chunk 可以从父块回溯。",
            "第三段继续补充上下文。",
        ]
    )

    chunks = build_hierarchical_chunks("doc-test", text)
    counts = chunk_counts(chunks)

    assert counts["L1"] >= 1
    assert counts["L2"] >= 1
    assert counts["L3"] >= 1
    assert all(chunk.document_id == "doc-test" for chunk in chunks)
    assert all(chunk.parent_id is not None for chunk in chunks if chunk.level != "L1")


def test_upload_text_document_and_query_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={
                "file": (
                    "knowledge.md",
                    "# Nebulai\n\n这是一个用于验证 ingestion 的 Markdown 文档。\n\n它应该生成 L1/L2/L3 chunks。",
                    "text/markdown",
                )
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "processing"
        assert payload["chunk_counts"]["L3"] == 0

        status_response = _wait_for_document_status(client, payload["id"])
        list_response = client.get("/api/documents")

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["filename"] == "knowledge.md"
    assert status_payload["metadata"]["embedding_provider"] in {"mock-hash", "openai-compatible"}
    assert status_payload["metadata"]["embedding_status"] in {"completed", "degraded"}
    assert status_payload["metadata"]["vector_status"] in {"completed", "degraded"}
    assert list_response.status_code == 200
    assert any(document["id"] == payload["id"] for document in list_response.json()["documents"])


def test_upload_docx_document_and_query_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={
                "file": (
                    "knowledge.docx",
                    _minimal_docx_bytes(["Nebulai DOCX", "用于验证 DOCX ingestion。"]),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "processing"

        status_response = _wait_for_document_status(client, payload["id"])

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["filename"] == "knowledge.docx"
    assert status_payload["metadata"]["chunk_counts"]["L3"] >= 1


def test_docx_ingestion_preserves_tables_headers_and_footers() -> None:
    result = ingest_text_document(
        "structured.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _structured_docx_bytes(),
        document_id="docx-structured",
    )

    assert "页眉中的合同编号" in result.text
    assert "员工姓名=张三" in result.text
    assert "月薪=10000" in result.text
    assert "页脚中的保密提示" in result.text
    assert result.chunk_counts["L3"] >= 1


def test_upload_pdf_document_and_query_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={
                "file": (
                    "knowledge.pdf",
                    _minimal_pdf_bytes("Nebulai PDF ingestion test"),
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "processing"

        status_response = _wait_for_document_status(client, payload["id"])

    assert status_response.status_code == 200
    assert status_response.json()["filename"] == "knowledge.pdf"


def test_upload_csv_document_and_query_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={
                "file": (
                    "employees.csv",
                    "姓名,部门,月薪\n张三,研发,10000\n李四,销售,9000\n",
                    "text/csv",
                )
            },
        )

        assert response.status_code == 200
        payload = response.json()
        status_response = _wait_for_document_status(client, payload["id"])

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["filename"] == "employees.csv"
    assert status_payload["metadata"]["chunk_counts"]["L3"] >= 1


def test_xlsx_ingestion_extracts_sheet_rows() -> None:
    result = ingest_text_document(
        "payroll.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _minimal_xlsx_bytes(
            "工资表",
            [
                ["姓名", "部门", "月薪"],
                ["张三", "研发", "10000"],
                ["李四", "销售", "9000"],
            ],
        ),
        document_id="xlsx-payroll",
    )

    assert "[XLSX sheet: 工资表]" in result.text
    assert "姓名=张三" in result.text
    assert "月薪=10000" in result.text
    assert result.chunk_counts["L3"] >= 1


def test_upload_rejects_unsupported_document_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            files={"file": ("image.png", b"not really an image", "image/png")},
        )

    assert response.status_code == 400
    assert "Supported document types" in response.json()["detail"]


def test_delete_uploaded_document_removes_status() -> None:
    with TestClient(app) as client:
        upload_response = client.post(
            "/api/documents",
            files={
                "file": (
                    "delete-me.md",
                    "# Delete me\n\nThis document should be removed.",
                    "text/markdown",
                )
            },
        )
        document_id = upload_response.json()["id"]
        _wait_for_document_status(client, document_id)

        delete_response = client.delete(f"/api/documents/{document_id}")
        status_response = client.get(f"/api/documents/{document_id}")
        list_response = client.get("/api/documents")

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    assert status_response.status_code == 404
    assert all(document["id"] != document_id for document in list_response.json()["documents"])


def test_retry_uploaded_document_reindexes_existing_chunks() -> None:
    with TestClient(app) as client:
        upload_response = client.post(
            "/api/documents",
            files={
                "file": (
                    "retry-me.md",
                    "# Retry me\n\nThis document should be re-indexed.",
                    "text/markdown",
                )
            },
        )
        document_id = upload_response.json()["id"]
        _wait_for_document_status(client, document_id)

        retry_response = client.post(f"/api/documents/{document_id}/retry")
        retry_status_response = _wait_for_document_status(client, document_id)

    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "processing"
    assert retry_status_response.status_code == 200
    retry_status = retry_status_response.json()
    assert retry_status["status"] == "completed"
    assert retry_status["metadata"]["retry_reason"] == "manual"


def test_mock_embedding_is_deterministic_and_normalized() -> None:
    provider = EmbeddingProvider(dimension=16)

    first = provider.embed_text("alpha beta alpha")
    second = provider.embed_text("alpha beta alpha")

    assert first == second
    assert len(first) == 16
    assert sum(value * value for value in first) == approx(1.0)


def test_remote_embedding_failure_falls_back_to_mock() -> None:
    provider = EmbeddingProvider(
        dimension=16,
        provider="openai-compatible",
        api_key="test-key",
        base_url="http://127.0.0.1:1/v1",
        timeout_seconds=0.01,
    )

    result = provider.embed_documents_with_metadata(["alpha beta"])

    assert result.status == "degraded"
    assert result.provider == "mock-hash"
    assert result.message.startswith("Embedding provider failed")
    assert len(result.vectors) == 1
    assert len(result.vectors[0]) == 16
    assert sum(value * value for value in result.vectors[0]) == approx(1.0)


def test_remote_embedding_can_omit_dimensions(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return b'{"data":[{"index":0,"embedding":[1.0,0.0]}]}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        import json

        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = EmbeddingProvider(
        dimension=2,
        provider="openai-compatible",
        model="BAAI/bge-m3",
        base_url="https://api.siliconflow.cn/v1",
        api_key="test-key",
        send_dimensions=False,
    )

    result = provider.embed_documents_with_metadata(["alpha"])

    assert result.status == "completed"
    assert "dimensions" not in captured_payload
    assert result.vectors == [[1.0, 0.0]]


def test_milvus_collection_dimension_is_read_from_schema_description() -> None:
    description = {
        "schema": {
            "fields": [
                {"name": "chunk_id", "params": {"max_length": "64"}},
                {"name": "dense_vector", "params": {"dim": "1024"}},
            ]
        }
    }

    assert _collection_dense_vector_dim(description) == 1024


def test_milvus_store_migrates_collection_missing_workspace_fields(monkeypatch) -> None:
    class FakeSchema:
        def add_field(self, **kwargs):
            return None

        def add_function(self, function):
            return None

    class FakeIndexParams:
        def add_index(self, **kwargs):
            return None

    class FakeClient:
        def __init__(self) -> None:
            self.created_collection: str | None = None

        def has_collection(self, collection_name: str, timeout: float):
            return collection_name == "nebulai_chunks"

        def describe_collection(self, collection_name: str):
            assert collection_name == "nebulai_chunks"
            return {
                "schema": {
                    "fields": [
                        {"name": "chunk_id", "params": {"max_length": "64"}},
                        {"name": "document_id", "params": {"max_length": "64"}},
                        {"name": "dense_vector", "params": {"dim": "384"}},
                    ]
                }
            }

        def create_schema(self, auto_id: bool, enable_dynamic_field: bool):
            assert auto_id is False
            assert enable_dynamic_field is False
            return FakeSchema()

        def prepare_index_params(self):
            return FakeIndexParams()

        def create_collection(self, collection_name: str, **kwargs):
            self.created_collection = collection_name

    fake_pymilvus = SimpleNamespace(
        DataType=SimpleNamespace(VARCHAR="varchar", INT64="int64", FLOAT_VECTOR="float", SPARSE_FLOAT_VECTOR="sparse"),
        Function=lambda **kwargs: kwargs,
        FunctionType=SimpleNamespace(BM25="bm25"),
    )
    monkeypatch.setitem(__import__("sys").modules, "pymilvus", fake_pymilvus)

    client = FakeClient()
    store = MilvusStore("http://localhost:19530", "nebulai_chunks")

    store._ensure_collection(client)

    assert store.collection_name == "nebulai_chunks_workspace"
    assert client.created_collection == "nebulai_chunks_workspace"


def _minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    paragraph_xml = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraph_xml}</w:body>"
        "</w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
        )
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _structured_docx_bytes() -> bytes:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>正文段落</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>员工姓名</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>月薪</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>张三</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>10000</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        "</w:body>"
        "</w:document>"
    )
    header_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:r><w:t>页眉中的合同编号</w:t></w:r></w:p>"
        "</w:hdr>"
    )
    footer_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:r><w:t>页脚中的保密提示</w:t></w:r></w:p>"
        "</w:ftr>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/header1.xml", header_xml)
        archive.writestr("word/footer1.xml", footer_xml)
    return buffer.getvalue()


def _minimal_xlsx_bytes(sheet_name: str, rows: list[list[str]]) -> bytes:
    shared_strings: list[str] = []
    string_indexes: dict[str, int] = {}
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            if value not in string_indexes:
                string_indexes[value] = len(shared_strings)
                shared_strings.append(value)
            cell_ref = f"{_excel_column(column_index)}{row_index}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{string_indexes[value]}</v></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
    return buffer.getvalue()


def _excel_column(index: int) -> str:
    result = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _wait_for_document_status(client: TestClient, document_id: str):
    response = client.get(f"/api/documents/{document_id}")
    for _ in range(10):
        if response.json()["status"] != "processing":
            return response
        time.sleep(0.05)
        response = client.get(f"/api/documents/{document_id}")
    return response


def _minimal_pdf_bytes(text: str) -> bytes:
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(f'BT /F1 18 Tf 72 720 Td ({escaped_text}) Tj ET')} >>\nstream\n"
        f"BT /F1 18 Tf 72 720 Td ({escaped_text}) Tj ET\nendstream".encode(),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)
