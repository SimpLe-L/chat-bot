from dataclasses import dataclass
from typing import Any

from nebulai.core.config import settings
from nebulai.rag.chunking import IngestedChunk
from nebulai.rag.embeddings import embedding_provider


@dataclass(frozen=True)
class MilvusIndexResult:
    status: str
    inserted_count: int
    collection: str
    message: str
    embedding_status: str
    embedding_provider: str
    embedding_message: str


@dataclass(frozen=True)
class MilvusDeleteResult:
    status: str
    collection: str
    message: str


class MilvusStore:
    def __init__(self, uri: str, collection_name: str) -> None:
        self._uri = uri
        self._collection_name = collection_name
        self._client: Any | None = None
        self._available = False

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def client(self) -> Any:
        return self._get_client()

    async def index_leaf_chunks(self, chunks: list[IngestedChunk]) -> MilvusIndexResult:
        leaf_chunks = [chunk for chunk in chunks if chunk.level == "L3"]
        if not leaf_chunks:
            return MilvusIndexResult(
                "skipped",
                0,
                self._collection_name,
                "No L3 leaf chunks to index.",
                "skipped",
                embedding_provider.mode,
                "No text required embedding.",
            )

        try:
            client = self._get_client()
            self._ensure_collection(client)
            embedding_result = embedding_provider.embed_documents_with_metadata([chunk.text for chunk in leaf_chunks])
            rows = [
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "parent_id": chunk.parent_id or "",
                    "level": chunk.level,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "dense_vector": vector,
                }
                for chunk, vector in zip(leaf_chunks, embedding_result.vectors, strict=True)
            ]
            client.upsert(collection_name=self._collection_name, data=rows, timeout=settings.milvus_timeout_seconds)
            return MilvusIndexResult(
                "completed",
                len(rows),
                self._collection_name,
                f"L3 leaf chunks indexed into Milvus with {embedding_result.provider} dense embeddings and BM25 sparse function.",
                embedding_result.status,
                embedding_result.provider,
                embedding_result.message,
            )
        except Exception as exc:
            return MilvusIndexResult(
                "degraded",
                0,
                self._collection_name,
                f"Milvus indexing skipped: {exc}",
                "degraded",
                embedding_provider.mode,
                f"Embedding/vector indexing could not complete: {exc}",
            )

    async def delete_document(self, document_id: str) -> MilvusDeleteResult:
        try:
            client = self._get_client()
            if not client.has_collection(self._collection_name, timeout=settings.milvus_timeout_seconds):
                return MilvusDeleteResult(
                    "skipped",
                    self._collection_name,
                    "Milvus collection does not exist; no vectors to delete.",
                )

            escaped_document_id = document_id.replace("\\", "\\\\").replace('"', '\\"')
            client.delete(
                collection_name=self._collection_name,
                filter=f'document_id == "{escaped_document_id}"',
                timeout=settings.milvus_timeout_seconds,
            )
            return MilvusDeleteResult(
                "completed",
                self._collection_name,
                "Document vectors deleted from Milvus.",
            )
        except Exception as exc:
            return MilvusDeleteResult(
                "degraded",
                self._collection_name,
                f"Milvus vector deletion skipped: {exc}",
            )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("pymilvus is not installed; install apps/api[rag] to enable vector indexing.") from exc

        self._client = MilvusClient(uri=self._uri, timeout=settings.milvus_timeout_seconds)
        return self._client

    def _ensure_collection(self, client: Any) -> None:
        if self._available:
            return
        if client.has_collection(self._collection_name, timeout=settings.milvus_timeout_seconds):
            existing_dim = _collection_dense_vector_dim(client.describe_collection(self._collection_name))
            if existing_dim is not None and existing_dim != settings.embedding_dimension:
                raise RuntimeError(
                    f"Milvus collection {self._collection_name} dense_vector dimension is {existing_dim}, "
                    f"but EMBEDDING_DIMENSION is {settings.embedding_dimension}. "
                    "Drop/recreate the collection and retry document indexing after changing embedding models."
                )
            self._available = True
            return

        from pymilvus import DataType, Function, FunctionType

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="level", datatype=DataType.VARCHAR, max_length=8)
        schema.add_field(field_name="ordinal", datatype=DataType.INT64)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096, enable_analyzer=True)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=settings.embedding_dimension)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25_emb",
                input_field_names=["text"],
                output_field_names=["sparse_vector"],
                function_type=FunctionType.BM25,
            )
        )

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
        )
        client.create_collection(
            collection_name=self._collection_name,
            schema=schema,
            index_params=index_params,
            timeout=settings.milvus_timeout_seconds,
        )
        self._available = True


milvus_store = MilvusStore(settings.milvus_uri, settings.milvus_collection)


def _collection_dense_vector_dim(description: Any) -> int | None:
    fields = []
    schema = _value(description, "schema")
    schema_fields = _value(schema, "fields") if schema is not None else None
    top_level_fields = _value(description, "fields")
    if isinstance(schema_fields, list):
        fields.extend(schema_fields)
    if isinstance(top_level_fields, list):
        fields.extend(top_level_fields)

    for field in fields:
        name = _value(field, "name") or _value(field, "field_name")
        if name != "dense_vector":
            continue

        dim = _value(field, "dim")
        if dim is not None:
            return _to_int(dim)

        for params_key in ("params", "type_params"):
            params = _value(field, params_key)
            dim = _param_value(params, "dim")
            if dim is not None:
                return _to_int(dim)
    return None


def _value(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _param_value(params: Any, key: str) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return params.get(key)
    if isinstance(params, list):
        for item in params:
            item_key = _value(item, "key")
            if item_key == key:
                return _value(item, "value")
    return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
