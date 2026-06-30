# Regression Checklist

日期：2026-06-30

目标：验证 `nebulai bot` 从知识库上传到 RAG 流式问答的主流程，以及 provider、队列、会话恢复和 UI 操作是否可用。

## 1. 启动前检查

```bash
pnpm install
.venv/bin/python -m pip install -e 'apps/api[dev,rag]'
docker compose up -d
pnpm --filter @nebulai/api dev
pnpm --filter @nebulai/web dev
```

验收：

- `curl http://localhost:8000/api/health` 返回 `status=ok`。
- `curl http://localhost:8000/api/providers/status` 返回 embedding、llm、rerank 三类状态。
- 如果已填写真实 key，执行 `curl "http://localhost:8000/api/providers/status?live=true"`，确认真实 provider 不返回 `failed`。

## 2. Provider 配置验证

`.env` 中有三组入口：

- `OPENAI_API_KEY`：同一个 key 同时给 LLM 和 embedding 使用。
- `LLM_API_KEY`：只给 chat completions 使用，优先级高于 `OPENAI_API_KEY`。
- `EMBEDDING_API_KEY`：只给 embeddings 使用，优先级高于 `OPENAI_API_KEY`。
- `RERANK_API_KEY` / `JINA_API_KEY`：可选；不填时 rerank 走 Milvus RRF 顺序。SiliconFlow rerank 可通过 `RERANK_PROVIDER=siliconflow`、`RERANK_URL=https://api.siliconflow.cn/v1/rerank` 配置。

修改 `.env` 后必须重启 API。前端右侧 `Providers` 面板默认只显示配置状态；点击刷新按钮才执行 live verify。

## 3. Ingestion 队列验证

步骤：

1. 在右侧 `Knowledge` 面板上传 `.md`、`.docx`、`.pdf`、`.csv` 或 `.xlsx`。
2. 观察文档卡片中的进度条、`job`、`embedding`、`vector`、`provider`。
3. 调用 `curl http://localhost:8000/api/ingestion/jobs` 查看持久化任务。
4. 上传大文档后重启 API，确认 queued/running job 会恢复处理。
5. 点击文档卡片的重试按钮，确认会创建新的 `vector_retry` job。

验收：

- 上传接口先返回 `processing`。
- job 从 `queued/running` 进入 `completed` 或明确 `failed`。
- 文档最终显示 `completed`，L1/L2/L3 数量不为 0。
- CSV/XLSX 表格应能在来源 excerpt/context 中看到表头、行号和 `列名=值`。
- DOCX 表格、页眉页脚等结构化文本应能进入 chunk。
- Milvus 不可用时文档仍应显示明确 degraded/skipped 信息，而不是接口崩溃。

## 4. Chat RAG 验证

步骤：

1. 针对刚上传文档提问。
2. 检查 token 是否逐步出现。
3. 检查 `RAG Trace` 是否包含 question analysis、retrieval、rewrite、二次 retrieval、rerank、synthesis。
4. 对复杂问题提问，例如：`请对比 Hybrid Search 和 Dense Search，并且分别说明 rerank 的影响`。
5. 检查二次 retrieval 详情里是否出现 `sub_agent_1`、`sub_agent_2` 等标识。

验收：

- SSE 完整输出 `accepted -> step/source/token -> done`。
- 复杂问题触发多查询并行检索。
- source 可显示文档标题、chunk 和分数。

## 5. 中断和恢复验证

步骤：

1. 提问后立即点击停止。
2. 检查 UI 不再追加 token。
3. 刷新页面。
4. 检查最近会话、消息历史和最新 RAG trace 是否恢复。
5. 重命名会话，再删除会话。

验收：

- 停止后后端 run 标记为 `cancelled`。
- 刷新后会话列表和消息不丢失。
- 切换会话后右侧 trace 反映该会话最近一次 run。

## 6. 前端 UI 回归

桌面宽度检查：

- 左侧会话列表不会遮挡标题。
- 中间消息流和 composer 不重叠。
- 右侧 Providers、Knowledge、RAG Trace 三段可读。
- 文档文件名、provider message、source excerpt 超长时不会撑破侧栏。
- 图标按钮 hover/disabled 状态可见。

移动宽度检查：

- 主聊天区可以正常提问和停止。
- 右侧面板当前是桌面专用；移动端不应遮挡聊天主流程。

命令验证：

```bash
pnpm --filter @nebulai/api test
pnpm --filter @nebulai/api lint
pnpm typecheck
pnpm --filter @nebulai/web build
```
