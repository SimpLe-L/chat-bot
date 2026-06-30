# Milvus Notes

Phase 0 only starts Milvus standalone through Docker Compose.

The target Phase 3 collection should use Milvus 2.5+ server-side BM25 Function:

- Store only L3 leaf chunks in Milvus.
- Keep L1/L2 parent chunks in PostgreSQL DocStore.
- Bind the raw `text` field to BM25 sparse vector generation.
- Run Dense + Sparse Hybrid Search.
- Merge candidates with RRF.
- Send the merged top-k to Jina Rerank when `JINA_API_KEY` exists.
- Fall back to dense-only retrieval when sparse or hybrid search fails.

