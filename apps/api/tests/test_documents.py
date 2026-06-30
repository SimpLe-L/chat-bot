from io import BytesIO
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pytest import approx

from nebulai.main import app
from nebulai.rag.chunking import build_hierarchical_chunks, chunk_counts
from nebulai.rag.embeddings import EmbeddingProvider
from nebulai.stores.milvus import _collection_dense_vector_dim


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
