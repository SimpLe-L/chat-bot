# nebulai bot

私有知识库 RAG 问答工作台。当前版本已具备可运行的登录页、前端聊天工作台、FastAPI SSE 后端、PostgreSQL/Redis/Milvus 本地基础设施、持久化 ingestion 队列、Milvus Hybrid Search、Corrective RAG、会话记忆、历史 trace 恢复、workspace 数据隔离和可配置 provider。

## Quick Start

```bash
pnpm install
python3 -m venv .venv
.venv/bin/python -m pip install -e 'apps/api[dev,rag]'
docker compose up -d
pnpm dev
```

默认端口：

- API: `http://localhost:8000`
- Web: `http://localhost:3000`，被占用时 Vite 会自动尝试下一个端口。

## Verify

```bash
pnpm --filter @nebulai/api test
pnpm --filter @nebulai/api lint
pnpm typecheck
pnpm --filter @nebulai/web build

curl http://localhost:8000/api/health
curl http://localhost:8000/api/providers/status
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"验证 RAG 流式问答","options":{"show_steps":true}}'
```

## `.env` Readiness

填完 `.env` 中缺失 key 不等于所有链路都会自动变成真实 provider。需要按目标区分：

- 自动化测试：不需要外部 key。
- 本地端到端 mock/degraded 测试：不需要外部 key，默认 `LLM_PROVIDER=mock`、`EMBEDDING_PROVIDER=mock-hash` 即可验证上传、检索、trace、停止生成和会话恢复。
- 真实 provider live 测试：需要有效 key，同时确认 provider、base URL、model 和 embedding 维度，再重启 API。

真实 provider 配置后执行：

```bash
curl "http://localhost:8000/api/providers/status?live=true"
```

## Auth

当前支持三类入口：

- 内部测试账号：本地开发模式可直接点击登录，账号为 `test@nebulai.local`；生产关闭 `EMAIL_LOGIN_DEV_MODE` 后该入口不可用。
- 邮箱验证码：本地开发默认返回 `dev_code`；生产部署设置 `EMAIL_LOGIN_DEV_MODE=false` 并配置 SMTP 后会真实发送邮件。
- GitHub OAuth：配置 `GITHUB_CLIENT_ID`、`GITHUB_CLIENT_SECRET` 后可用。
- Google OAuth：配置 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET` 后可用。

OAuth 回调地址需要在 provider 后台配置为：

```text
GitHub: http://localhost:8000/api/auth/oauth/github/callback
Google: http://localhost:8000/api/auth/oauth/google/callback
```

如果部署到正式域名，把上面的 host 替换为 `API_BASE_URL` 对应域名。

部署时至少需要修改：

```env
AUTH_SESSION_SECRET=足够长的随机密钥
OAUTH_STATE_COOKIE_NAME=nebulai_oauth_state
APP_BASE_URL=https://你的前端域名
API_BASE_URL=https://你的 API 域名
AUTH_COOKIE_SECURE=true
EMAIL_LOGIN_DEV_MODE=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=你的 SMTP 用户名
SMTP_PASSWORD=你的 SMTP 密码
GITHUB_CLIENT_ID=你的 GitHub OAuth Client ID
GITHUB_CLIENT_SECRET=你的 GitHub OAuth Client Secret
GOOGLE_CLIENT_ID=你的 Google OAuth Client ID
GOOGLE_CLIENT_SECRET=你的 Google OAuth Client Secret
```

所有会话、文档、chunks、RAG trace、ingestion jobs 和 Milvus 向量都会写入 `user_id/workspace_id`。如果从旧版 Milvus collection 升级，必须重建 collection 并重新上传文档，否则旧 collection 没有 `workspace_id` 字段，无法做向量层隔离。

## SiliconFlow

当前 `.env` 已经把 LLM、Embedding、Rerank 指向硅基流动。推荐把硅基流动 key 填到 `SILICONFLOW_API_KEY`，LLM/Embedding/Rerank 都会使用这个共享 key；也可以分别填 `LLM_API_KEY`、`EMBEDDING_API_KEY`、`RERANK_API_KEY`。

LLM：

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
SILICONFLOW_API_KEY=你的硅基流动 API Key
```

Embedding：

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_SEND_DIMENSIONS=false
```

Rerank：

```env
RERANK_PROVIDER=siliconflow
RERANK_URL=https://api.siliconflow.cn/v1/rerank
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_INSTRUCTION=Given a private knowledge base query, rank passages by relevance.
```

`BAAI/bge-m3` 是 1024 维；当前旧 Milvus collection 如果是 384 维，需要重建 collection 并重新上传文档。若改用支持 `dimensions` 参数的 Qwen3 embedding，可设置对应 `EMBEDDING_DIMENSION` 并把 `EMBEDDING_SEND_DIMENSIONS=true`。

## Current Scope

可验证能力：

- SSE 流式问答、停止生成、错误提示。
- 登录页：GitHub、Google、邮箱验证码；右上角用户头像菜单和退出登录。
- 基于 `workspace_id` 的会话、文档、trace、ingestion job 和 Milvus 检索隔离。
- 会话创建、重命名、删除、历史消息恢复。
- RAG trace 持久化与恢复。
- 文档上传、processing 轮询、删除、重试索引。
- txt/md/docx/pdf/csv/xlsx ingestion；PDF 优先使用 `pdfplumber` 做 layout/table 文本提取，缺失时回退 `pypdf`；当前不支持旧版二进制 `.xls`。
- L1/L2/L3 分块，L3 leaf chunks 写入 Milvus。
- Milvus Dense + BM25 Sparse Hybrid Search + RRF。
- Corrective RAG：`hyde`、`step_back`、`complex` 和并行二次检索。
- 可选 LLM/Embedding/Rerank provider live verify。

更多细节：

- 架构：`ARCHITECTURE.md`
- 当前进度：`PROCESS.md`
- Provider smoke：`docs/PROVIDER_SMOKE.md`
- 手工回归：`docs/REGRESSION_CHECKLIST.md`
