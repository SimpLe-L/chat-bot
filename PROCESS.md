# PROCESS.md

日期：2026-06-30

## 当前状态

`nebulai bot` 当前已经不是纯 mock 骨架，而是可本地运行的 LangGraph RAG 工作台：

- 前端：TanStack Start + React + Tailwind + assistant-ui runtime，支持聊天、停止生成、会话恢复、Knowledge/Providers/RAG Trace 侧栏。
- 后端：FastAPI + SSE，`/api/chat/stream` 已串联 LangGraph RAG 节点。
- 存储：PostgreSQL 持久化会话、消息、文档、chunks、RAG run/steps/sources、ingestion jobs；Redis 负责 run 状态和取消信号，失败时降级内存。
- 知识库：上传 txt/md/docx/pdf 后进入持久化 ingestion 队列，三级分块，L3 leaf chunks 写入 Milvus。
- 检索：Milvus Dense + BM25 Sparse Hybrid Search + RRF，失败时降级 dense/mock，并在 trace 中记录。
- RAG：Corrective RAG 已支持 `hyde`、`step_back`、`complex`；复杂问题先经过 question planner 拆成子问题，再并行执行 sub-agent 检索链路，并在 trace 中标记 `sub_agent_1/2/3`。
- Provider：LLM、Embedding 支持 OpenAI-compatible API；Rerank 支持通用 `RERANK_*` 配置并兼容旧 `JINA_*`；缺 key 或调用失败时保留可观测降级。
- SiliconFlow：`.env` 已配置 LLM、`BAAI/bge-m3` embedding、`BAAI/bge-reranker-v2-m3` rerank；填 `SILICONFLOW_API_KEY` 后可做 live verify。
- 记忆与恢复：同一 session 会更新 `sessions.summary`，切换/刷新页面可恢复历史消息和最近 RAG trace。

## 当前验收情况

最近已验证通过：

```bash
pnpm install
.venv/bin/python -m pip install -e 'apps/api[dev,rag]'
docker compose up -d
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

本轮文档精简后已重新验证：

```bash
pnpm --filter @nebulai/api test
pnpm typecheck
```

结果：API 测试 `29 passed`；shared/web TypeScript typecheck 通过。

本轮 SiliconFlow embedding/rerank 接入后已重新验证：

```bash
pnpm --filter @nebulai/api test
pnpm --filter @nebulai/api lint
pnpm typecheck
```

结果：API 测试 `31 passed`；API compileall 通过；shared/web TypeScript typecheck 通过。`collect_provider_status(live=False)` 显示 embedding 为 `openai-compatible`、rerank 为 `siliconflow`，当前因未填 `SILICONFLOW_API_KEY` 仍处于 missing/not_configured 状态。

本轮前端 UI 修复：

- 将 `apps/web/src/styles.css` 显式引入 TanStack 根路由，避免 Start/Router SSR 页面出现裸 HTML。
- 补全 TanStack Start 根路由文档壳：`<html><head><HeadContent /></head><body><Outlet /><Scripts /></body></html>`，确保 SSR 返回的 HTML 直接包含 stylesheet link 和客户端脚本。
- 优化聊天工作台布局：左侧会话、中间消息流、右侧 Providers/Knowledge/RAG Trace inspector，保持 assistant-ui runtime + ComposerPrimitive 输入路径。
- 验证 `pnpm --filter @nebulai/web build` 和 `pnpm typecheck` 通过；HTTP 检查确认 dev 页面 `<head>` 输出 `@tanstack-start/styles.css` stylesheet link。

本轮启动崩溃修复：

- 修复 assistant-ui external-store message adapter：只有 assistant message 携带 `status`，user message 不再写入 `status`，避免启动或恢复历史消息时报 `status is only supported for assistant messages`。
- 固定 SSR 首屏 fallback 会话的初始 id 和 timestamp，避免服务端/客户端各自生成 `crypto.randomUUID()`、`new Date()` 导致 React hydration mismatch。
- 验证 `pnpm --filter @nebulai/web typecheck`、`pnpm --filter @nebulai/web build` 通过；dev server 页面实际打开后不再显示错误边界。

本轮工作台布局和 provider 状态修复：

- 将前端主工作台改为固定一屏：`body/#root/main` 不再随内容撑高，左侧会话列表、中间消息流、右侧 inspector 各自内部滚动。
- 调整消息流布局：用户消息靠右显示，bot 回复靠左显示，长文本在气泡内换行。
- 修复后端配置读取：FastAPI `Settings` 显式读取仓库根目录 `.env`，避免从 `apps/api` 启动时读不到用户已配置的 LLM/Embedding/Rerank。
- 新增 API 测试环境隔离：测试进程强制使用 mock provider 和 384 维 embedding，避免用户本地真实 `.env` 或 Milvus collection 维度影响自动化测试。
- 验证 `GET /api/providers/status` 返回 `overall=ready`，embedding/llm 为 `openai-compatible configured`，rerank 为 `siliconflow configured`。
- 验证 `pnpm --filter @nebulai/api test`、`pnpm --filter @nebulai/api lint`、`pnpm typecheck`、`pnpm --filter @nebulai/web build` 通过。浏览器插件拒绝访问当前 `localhost:3001`，因此本轮未完成自动化视觉截图验证。

本轮文档索引降级可观测性修复：

- 确认 `chn222798.pdf` 已成功解析和三级分块：`L1=6`、`L2=16`、`L3=37`，问题不是 PDF 上传或解析失败。
- 定位降级原因：当前 `.env` 使用 `BAAI/bge-m3`，`EMBEDDING_DIMENSION=1024`，但本地已有 Milvus collection `nebulai_chunks` 仍是旧的 `384` 维。
- 后端在写入向量前增加 collection 维度检查，遇到维度不匹配时输出明确原因，而不是直接透出 Milvus 的扁平向量长度错误。
- 前端 Knowledge 文档卡片在 `embedding/vector degraded` 时显示 `vector_message` / `embedding_message`，避免只显示状态词而看不到原因。
- 已对 `chn222798.pdf` 执行一次 retry，当前 metadata 明确显示：`Milvus collection nebulai_chunks dense_vector dimension is 384, but EMBEDDING_DIMENSION is 1024`。
- 验证 `pnpm --filter @nebulai/api test`、`pnpm --filter @nebulai/api lint`、`pnpm typecheck`、`pnpm --filter @nebulai/web build` 通过。

本轮本地数据重建和测试数据清理：

- 按当前 `.env` 的 `EMBEDDING_DIMENSION=1024` 重建本地 Milvus collection `nebulai_chunks`。
- 清空 PostgreSQL 本地聊天测试数据：`sessions=0`、`messages=0`、`rag_runs=0`。
- 清理知识库测试文档：删除全部 `.md/.markdown` 文档，以及测试生成的 `knowledge.pdf`、`knowledge.docx`；当前仅保留 `chn222798.pdf` 和 `劳动合同【廖雷】 .pdf`。
- 对保留的两个 PDF 重新执行向量索引：`chn222798.pdf` 写入 `37` 条 L3 向量，`劳动合同【廖雷】 .pdf` 写入 `23` 条 L3 向量。
- 验证 Milvus `nebulai_chunks` 的 `dense_vector` 维度为 `1024`。

本轮检索证据截断修复：

- 定位“来源中截断”原因：Milvus 命中 L3 后只把 `text[:240]` 写入 `RagSource.excerpt`，而回答 prompt、rerank、纠错评分也复用了这个短摘要。
- 扩展 `RagSource`：保留 `excerpt` 作为前端展示摘要，同时新增 `context`、`contextChunkId`、`contextLevel`、`parentId` 作为生成和评分用证据上下文。
- 检索命中 L3 后会从 PostgreSQL 回溯父级 chunk，优先把 L2 父块作为 `context`；PostgreSQL 不可用时退回 Milvus 返回的完整 L3 文本。
- answer prompt、mock answer、rerank payload、corrective relevance/grader 已统一优先使用 `source.context || source.excerpt`。
- 降低 mock fallback source 的分数，避免 Milvus 维度不匹配等降级场景下，mock source 误阻止复杂问题的二次检索。
- 验证 `pnpm --filter @nebulai/api test`、`pnpm --filter @nebulai/api lint`、`pnpm typecheck` 通过。

本轮企业级检索失败边界和测试隔离修复：

- 调整检索失败策略：Milvus Hybrid 和 Dense 都失败时不再返回 mock source，改为 `retrieval_failed` + 空来源 + 明确错误原因，避免维度不匹配等索引事故被伪造来源遮蔽。
- 新增测试锁定边界：检索异常时 `retrieve_sources()` 必须返回空来源，不能用 mock source 伪装知识库命中。
- 新增 `TESTING=true` 配置；测试模式下 FastAPI lifespan 不连接真实 PostgreSQL/Redis，也不启动 ingestion queue。
- API 测试环境把 Milvus 指向不可用本地端口，避免测试访问真实 `nebulai_chunks` collection。
- 清理本地测试残留：删除测试会话 `验证 LangGraph RAG 节点` 2 条，删除测试文档 `knowledge.md/docx/pdf`、`retry-me.md` 共 8 条，并从 Milvus 删除对应向量。
- 清理后确认 PostgreSQL 仅剩当前业务会话 1 条、文档 2 个：`chn222798.pdf` 和 `劳动合同【廖雷】 .pdf`；Milvus 仅剩这两个文档的向量：37 + 23 条。
- 验证 `pnpm --filter @nebulai/api test`、`pnpm --filter @nebulai/api lint`、`pnpm typecheck` 通过。

本轮回答引用交互优化：

- 前端 bot 消息会解析回答正文里的 `[1]`、`[2]` 等引用标记，并渲染为可点击来源按钮。
- 点击引用会跳转到当前回答下方对应的来源卡片，用户可以直接看到文档名、chunk id、context level、score、rerank 和摘录内容。
- bot 最新回答下方新增可折叠的“检索过程与引用来源”面板，展示最近 RAG steps 和 Sources，减少只看到“来源[2]”但不知道对应文档的问题。
- 用户消息保持纯文本，不会误解析用户输入里的方括号编号。
- 验证 `pnpm typecheck`、`pnpm --filter @nebulai/web build` 通过。

本轮架构精简：

- 梳理文档与实现后，确认 `rag/graph.py` 存在 LangGraph 节点与 direct fallback 双份业务流程，后续容易出现节点漂移。
- 将问题分析、检索、纠错检索、rerank、答案规划抽成共享节点函数；LangGraph 和 direct fallback 只保留调度差异。
- 为 `build_langgraph_app()` 增加单进程缓存，避免每次请求重复 import/compile graph。
- 删除 `retrieval.py` 中已不符合当前边界的未用 `mock_source()`；检索失败继续保持 `retrieval_failed` + 空来源。
- 修正 `ARCHITECTURE.md` 和 `AGENTS.md` 中过时的 `mock 检索`、`LangGraph Send API` 表述。
- 验证 `pnpm --filter @nebulai/api test`、`pnpm --filter @nebulai/api lint`、`pnpm typecheck` 通过；API 测试 `34 passed`。

本轮 RAG 知识文档与 design 对照：

- 新增根目录 `RAG_KNOWLEDGE_AND_GAP_ANALYSIS.md`，整理常见 RAG 类型、RAG 评估测试方法、核心知识点。
- 对照 `design.md` 的 12 个要点标注当前完成度：已实现、部分实现、需要补齐。
- 当时明确的主要差距包括：尚未使用 LangGraph `Send API` 完整子 Agent 图、RAG step 不是 queue 驱动的工具执行实时事件、Synthesis 仍未拆成独立证据合成节点、会话摘要仍是规则式压缩、Auto-merging 仍是父块回溯而非阈值合并；这些已在后续 P2/P1/P4/P5 基础版中补齐。
- 本轮只新增文档和进度记录，未修改运行代码；无需重新跑自动化测试。

本轮 P0 RAG eval 优化：

- 按 `RAG_KNOWLEDGE_AND_GAP_ANALYSIS.md` 第 5 节建议，优先补齐 RAG eval 基础闭环。
- 新增 `apps/api/evals/rag_evalset.jsonl`，作为可版本化 JSONL 评估集；case 支持 `gold_chunk_ids`、`gold_document_ids`、`gold_document_titles`、`gold_context_terms`、`tags`、`difficulty`。
- 新增 `nebulai.evals.retrieval_eval`，支持运行检索评估并输出 JSON 指标：`Recall@k`、`Precision@k`、`HitRate@k`、`MRR`、`nDCG@k` 和每个 case 的命中来源。
- 新增 `pnpm --filter @nebulai/api eval:retrieval` 命令，默认读取 `apps/api/evals/rag_evalset.jsonl`，不依赖当前 shell 工作目录。
- 新增 `apps/api/tests/test_retrieval_eval.py`，锁定 evalset 读取、标题/上下文 gold 匹配、rank metrics 和 aggregate 平均值。
- 当前本地运行 `pnpm --filter @nebulai/api eval:retrieval` 可输出完整 JSON；本轮 3 个 seed case 在当前本地索引下基线为 `hit_rate@5=0.0`、`recall@5=0.0`、`mrr=0.0`，后续需要用真实稳定文档 id/chunk id 扩充 evalset。
- 验证 `pnpm --filter @nebulai/api test` 通过，API 测试 `38 passed`；补充验证 `pnpm --filter @nebulai/api test tests/test_retrieval_eval.py` 为 `4 passed`，`pnpm --filter @nebulai/api lint` 通过。

本轮 P3 Synthesis 基础版优化：

- 新增 `nebulai.rag.synthesis`，在 answer provider 前增加独立 synthesis 步骤。
- `synthesize_sources()` 会按 `contextChunkId || chunkId` 去重，保留当前 rerank 顺序，默认最多取 5 条证据，返回父块扩展数量与去重/截断数量。
- 无来源时 synthesis 返回 warning，并明确要求答案说明知识库依据不足、不能伪造来源。
- `run_rag_workflow()` 现在在 `plan_answer` 节点产出 `SynthesisResult`；SSE `source` 事件和 answer provider 都使用 synthesis 后的 sources，trace 的“答案合成”步骤展示 synthesis message。
- `build_answer_prompt()` 增加引用绑定要求：使用来源支持结论时必须在句末标注 `[1]`、`[2]`；无候选来源时必须说明“当前知识库依据不足”。
- mock answer provider 在有来源时输出带编号的上下文摘要，在无来源时明确说明无法基于私有知识库确认答案。
- 新增 `apps/api/tests/test_synthesis.py`，覆盖证据去重、无来源 warning、source 截断；扩展 answer prompt/mock answer 测试。
- 验证 `pnpm --filter @nebulai/api test` 通过，API 测试 `41 passed`；`pnpm --filter @nebulai/api lint`、`pnpm typecheck` 通过。

本轮 P2/P1/P4/P5 连续优化：

- P2 question planner：新增 `nebulai.rag.planning`，支持 `simple/multi_hop/comparison/broad_summary` 分类、deterministic 子问题拆解和可选 OpenAI-compatible LLM JSON planner。
- P2 LangGraph Send API：复杂问题不再只跑 rewritten query 检索；LangGraph graph 使用 conditional `Send("sub_agent_retrieve", ...)` 原生 fan-out，每个 sub-agent 执行 `retrieve -> corrective assess -> optional secondary retrieval -> rerank`，再 fan-in 回主链路。
- P2 trace：复杂问题会输出“问题拆解”和每个 `Sub-Agent 检索` 步骤；sub-agent 失败或无来源时仍以 warning trace 记录。
- P1 event queue：`run_rag_stream()` 现在会在 workflow 后台 task 执行期间消费 `event_queue`，节点执行时即时推送 `question_analysis/retrieval/rewrite/sub-agent/rerank/synthesis` step，而不是等 workflow 完成后批量组装。
- P4 LLM 摘要记忆：新增 `build_session_summary_with_llm()`，有真实 LLM key 时生成结构化摘要；无 key、调用失败或测试环境下回退现有 deterministic 摘要。
- P5 Auto-merging：`expand_source_contexts()` 在多个 L2 命中同一 L1 时自动拉取 L1 父块作为上下文；单个命中仍保持 L2 父块回溯。
- 新增 `apps/api/tests/test_planning.py`，扩展 `test_chat.py` 覆盖 question planner、sub-agent rerank、LLM summary fallback 和 L1 auto-merging。
- 验证 `pnpm --filter @nebulai/api test` 通过，API 测试 `47 passed`；`pnpm --filter @nebulai/api lint`、`pnpm typecheck` 通过。Send API 改造后补充验证 `test_rag_workflow_executes_real_langgraph_nodes` 和 `test_chat_stream_contains_langgraph_rag_step` 均通过。

已知验证边界：

- 自动化测试和 mock/degraded 本地链路不需要真实 LLM/Embedding/Rerank key。
- 真实 provider live smoke 需要填入有效 key、base URL、model，并重启 API。
- 如果更换 embedding 维度，必须重建 Milvus collection 并重新 ingestion；当前默认 collection 维度为 `384`。
- 当前 synthesis 已有独立证据整理节点，但还未做深度冲突检测、句级引用自动校验和 token 预算压缩。
- 当前 P2 已切换为 LangGraph `Send API` 原生 fan-out/fan-in；direct fallback 仍保留本地并行子链路。
- 当前 API 内置 ingestion worker；多实例部署前应拆出独立 worker，并增加 lease timeout / dead-letter queue。

## `.env` 是否填完就能测试

分三种情况看：

1. 本地自动化测试：不需要填外部 key。安装依赖并启动 Docker 基础设施后即可运行 `pnpm test`、`pnpm typecheck`、`pnpm --filter @nebulai/web build`。
2. 本地端到端 mock/degraded 测试：不需要真实 key。保持 `LLM_PROVIDER=mock`、`EMBEDDING_PROVIDER=mock-hash` 即可验证上传、检索、trace、停止生成、会话恢复。
3. 真实 provider live 测试：只填 key 还不够。还要确认 provider、base URL、model、`EMBEDDING_DIMENSION` 与当前 Milvus collection 匹配，然后重启 API 并执行 `GET /api/providers/status?live=true`。

## 硅基流动配置

硅基流动可按 OpenAI-compatible provider 接入。

当前 `.env` 已经配置为硅基流动 LLM + Embedding + Rerank。推荐把共享 key 填到 `SILICONFLOW_API_KEY`；如需拆分，也可以分别填 `LLM_API_KEY`、`EMBEDDING_API_KEY`、`RERANK_API_KEY`。

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

注意：`BAAI/bge-m3` 返回 1024 维。旧 collection 如果按默认 384 维创建过，需要清空/重建 Milvus collection 后重新上传文档。

Rerank：

```env
RERANK_PROVIDER=siliconflow
RERANK_URL=https://api.siliconflow.cn/v1/rerank
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_INSTRUCTION=Given a private knowledge base query, rank passages by relevance.
```

## 下一步

1. 用当前真实知识库补齐 `apps/api/evals/rag_evalset.jsonl` 的稳定 `gold_document_ids/gold_chunk_ids`，重新运行 `pnpm --filter @nebulai/api eval:retrieval` 建立非零检索基线。
2. 填入真实 provider 配置后运行 `curl "http://localhost:8000/api/providers/status?live=true"`，确认 LLM/Embedding/Rerank live 状态。
3. 用真实 provider 跑一次文档上传、问答、停止生成、会话恢复回归，按 `docs/REGRESSION_CHECKLIST.md` 验证。
4. 在真实 provider 下复测 LLM question planner、LLM session summary 和 rerank 质量，把失败样本写入 evalset。
5. 继续增强深层质量项：synthesis 冲突检测、句级引用校验、prompt budget packing、多实例 ingestion worker。

## 维护约定

- 每完成一个可验证任务，更新本文件的当前状态、验证记录和下一步。
- 不要移除缺 key 降级路径；真实 provider 失败必须在 trace/provider status 中可见。
- 前端继续保持工作台形态，优先可操作、可观测、可恢复，不做营销式页面。
