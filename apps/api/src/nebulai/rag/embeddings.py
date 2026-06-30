import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass
from typing import Any

from nebulai.core.config import settings


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    provider: str
    status: str
    message: str


class EmbeddingProvider:
    def __init__(
        self,
        dimension: int = settings.embedding_dimension,
        provider: str = settings.embedding_provider,
        model: str = settings.embedding_model,
        base_url: str = settings.embedding_base_url,
        api_key: str = settings.effective_embedding_api_key,
        send_dimensions: bool = settings.embedding_send_dimensions,
        timeout_seconds: float = settings.embedding_timeout_seconds,
    ) -> None:
        self.dimension = dimension
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.send_dimensions = send_dimensions
        self.timeout_seconds = timeout_seconds
        self._mock = HashEmbeddingProvider(dimension)

    @property
    def mode(self) -> str:
        if self._remote_enabled:
            return "openai-compatible"
        return "mock-hash"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents_with_metadata(texts).vectors

    def embed_documents_with_metadata(self, texts: list[str]) -> EmbeddingBatchResult:
        if not self._remote_enabled:
            return EmbeddingBatchResult(
                vectors=self._mock.embed_documents(texts),
                provider="mock-hash",
                status="completed",
                message="Generated deterministic mock hash embeddings.",
            )

        try:
            vectors = self._embed_remote(texts)
            return EmbeddingBatchResult(
                vectors=vectors,
                provider="openai-compatible",
                status="completed",
                message=f"Generated embeddings with model {self.model}.",
            )
        except Exception as exc:
            return EmbeddingBatchResult(
                vectors=self._mock.embed_documents(texts),
                provider="mock-hash",
                status="degraded",
                message=f"Embedding provider failed; fell back to mock-hash: {exc}",
            )

    def embed_text(self, text: str) -> list[float]:
        if self._remote_enabled:
            try:
                return self._embed_remote([text])[0]
            except Exception:
                return self._mock.embed_text(text)
        return self._mock.embed_text(text)

    @property
    def _remote_enabled(self) -> bool:
        return self.provider in {"openai", "openai-compatible"} and bool(self.api_key)

    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }
        if self.send_dimensions:
            payload["dimensions"] = self.dimension
        request = urllib.request.Request(
            url=f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))

        vectors = [item["embedding"] for item in sorted(body.get("data", []), key=lambda item: item["index"])]
        if len(vectors) != len(texts):
            raise RuntimeError(f"Embedding response returned {len(vectors)} vectors for {len(texts)} inputs.")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch: expected {self.dimension}, received {len(vector)}."
                )
        return vectors


class HashEmbeddingProvider:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _tokens(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def _tokens(text: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    return [token for token in normalized.split() if token]


embedding_provider = EmbeddingProvider()
