# Provider Smoke Guide

本文件用于验证真实 provider 是否可用，同时确认缺 key 或 provider 异常时系统仍能降级运行。

## 启动

```bash
pnpm install
.venv/bin/python -m pip install -e 'apps/api[dev,rag]'
docker compose up -d
pnpm dev:api
```

修改 `.env` 后必须重启 API。

## Provider 模式

### Mock/degraded 模式

不需要外部 key：

```env
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock-hash
JINA_API_KEY=
```

可验证上传、检索、trace、停止生成、会话恢复；LLM 输出为 mock token，embedding 为确定性 hash。

### OpenAI-compatible LLM

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

如果同一个 key 同时给 LLM 和 embedding 使用，也可以只填：

```env
OPENAI_API_KEY=sk-...
```

优先级：`LLM_API_KEY` 高于 `OPENAI_API_KEY`。

### OpenAI-compatible Embedding

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=sk-...
EMBEDDING_DIMENSION=384
```

优先级：`EMBEDDING_API_KEY` 高于 `OPENAI_API_KEY`。

注意：`EMBEDDING_DIMENSION` 必须和 Milvus collection 的 `dense_vector` 维度一致。当前默认 collection 是 `384` 维；如果改维度，需要重建 collection 并重新 ingestion。

### Generic Rerank

```env
RERANK_PROVIDER=jina
RERANK_API_KEY=jina_...
RERANK_URL=https://api.jina.ai/v1/rerank
RERANK_MODEL=
```

旧 `JINA_*` 变量仍然兼容：

```env
JINA_API_KEY=jina_...
JINA_RERANK_URL=https://api.jina.ai/v1/rerank
JINA_RERANK_MODEL=
```

Rerank key 不填时，系统保留 Milvus RRF 顺序，不影响主链路。

## SiliconFlow

### 当前推荐：LLM + Embedding + Rerank

```env
SILICONFLOW_API_KEY=你的硅基流动 API Key

LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash

EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_SEND_DIMENSIONS=false

RERANK_PROVIDER=siliconflow
RERANK_URL=https://api.siliconflow.cn/v1/rerank
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_INSTRUCTION=Given a private knowledge base query, rank passages by relevance.
```

如果不想使用共享 key，也可以分别填 `LLM_API_KEY`、`EMBEDDING_API_KEY`、`RERANK_API_KEY`。

### 硅基流动 Embedding 维度

`BAAI/bge-m3` 返回 1024 维，且不需要请求体中的 `dimensions` 字段，所以使用：

```env
EMBEDDING_DIMENSION=1024
EMBEDDING_SEND_DIMENSIONS=false
```

如果当前 Milvus collection 已按默认 `384` 维创建过，需要删除/重建 collection 并重新上传文档，否则向量写入或检索会降级。

如果改用支持 `dimensions` 的 Qwen3 embedding 模型，可设置模型支持的维度并打开：

```env
EMBEDDING_SEND_DIMENSIONS=true
```

### 硅基流动 Rerank

当前代码使用通用 `RERANK_*` 请求体，并解析 `results[index,relevance_score]`。如果 live verify 返回 `failed`，主链路仍会保留 Milvus RRF 顺序。

## 验证命令

配置状态，不调用外部 provider：

```bash
curl http://localhost:8000/api/providers/status
```

Live verify，会真实请求 provider：

```bash
curl "http://localhost:8000/api/providers/status?live=true"
```

上传文档：

```bash
curl -X POST http://localhost:8000/api/documents \
  -F file=@AGENTS.md

curl http://localhost:8000/api/documents
curl http://localhost:8000/api/ingestion/jobs
```

问答 smoke：

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"根据已上传知识库，概括 nebulai bot 的架构。","options":{"show_steps":true}}'
```

期望：

- `accepted -> step/source/token -> done` 完整输出。
- 真实 LLM 配置成功时，`synthesis` step 显示 OpenAI-compatible provider。
- 缺 key 或 provider 失败时，trace/provider status 中能看到 warning/degraded，不应导致请求崩溃。
- Rerank 未配置或失败时，source 保留 Milvus RRF 顺序。

## 故障回退测试

设置错误 endpoint 后重启 API：

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://127.0.0.1:1/v1
LLM_API_KEY=test-key
```

再次调用 `/api/chat/stream`。期望返回 LLM provider failed warning，并继续输出 mock token 和 `done`。
