# AGENTS.md

## 项目定位

项目名称：`nebulai bot`

`nebulai bot` 是一个基于 RAG 架构的私有知识库问答系统。系统支持上传或接入业务文档，通过文档解析、三级切分、向量化存储、混合检索、纠错型 RAG、多轮会话记忆和流式回答，帮助用户在私有知识中进行可追溯问答。

## 当前技术边界

- 前端：TanStack Start、React、TypeScript、Tailwind CSS、assistant-ui。
- 后端：FastAPI。选择 FastAPI 的原因是它与 Python RAG 生态、LangChain/LangGraph、异步流式输出和后台检索事件队列更直接匹配。
- RAG 编排：LangGraph/LangChain。
- 数据存储：PostgreSQL 存储会话、消息、文档元数据、检索过程记录；Redis 用于流式任务状态、中断信号和临时队列。
- 向量数据库：Milvus 2.5+，目标使用服务端原生 BM25 Function 实现 Dense + Sparse Hybrid Search。
- 包管理：pnpm monorepo。
- 本地基础设施：Docker Compose 管理 PostgreSQL、Redis、Milvus 及其依赖。

## 目录职责

```text
.
├── apps/
│   ├── web/                 # TanStack Start 前端应用
│   └── api/                 # FastAPI RAG/Chat API
├── packages/
│   └── shared/              # 前后端共享 TypeScript 类型和接口描述
├── design.md                # 原始技术设计要求
├── pic.png                  # 原始项目说明截图
├── ARCHITECTURE.md          # 架构与数据流
├── PROCESS.md               # 进度、验证记录和下一步
└── AGENTS.md                # 面向后续 AI/开发者的工作约定
```

## 开发原则

1. 先保证问答链路可运行，再逐步增强检索质量。
2. RAG 流程必须可观测：检索、重写、评分、rerank、来源和降级路径都要能在前端展开查看。
3. 流式回答必须可中断：前端使用 `AbortController`，后端在 SSE 生成器中响应断开和取消信号。
4. 检索必须支持降级：Hybrid Search 或稀疏向量失败时，降级为 Dense Search，并在过程事件中明确记录。
5. 知识库 ingestion 和 chat query 分开实现，避免上传/解析任务阻塞问答链路。
6. `PROCESS.md` 是当前进度账本。每完成一个可验证任务，都要更新已完成内容、验证方式、风险和下一步。
7. 当前文档 ingestion 支持 txt/md/docx/pdf/csv/xlsx；旧版二进制 `.xls` 和扫描件 OCR 仍是后续增强边界。

## 阶段拆分

### Phase 0：项目骨架

交付物：

- pnpm monorepo。
- `apps/web` TanStack Start 前端。
- `apps/api` FastAPI 后端。
- Docker Compose 基础设施。
- `.env.example` 和本地启动命令。

验收标准：

- `pnpm install` 可以安装依赖。
- `docker compose up -d` 可以启动 PostgreSQL、Redis、Milvus。
- 前端和后端可以分别启动。
- 前端可以调用后端 mock 流式问答接口。

### Phase 1：流式问答闭环

交付物：

- Chat UI：用户提问、消息展示、loading、错误提示、历史对话。
- SSE/ReadableStream 流式输出。
- 回答终止按钮。
- 后端 `/api/chat/stream` 输出 answer token、rag step、source、error、done 等事件。

验收标准：

- 用户输入问题后可以看到逐 token 回复。
- 检索过程在回答前或回答中实时展示。
- 点击停止后前端不再追加 token，后端生成器释放。
- 网络或服务错误时 UI 有明确提示。

### Phase 2：知识库 ingestion

交付物：

- 文档上传接口。
- 文档解析、清洗、三级分块。
- Leaf-only 向量化。
- 父块 DocStore。
- PostgreSQL 文档元数据。

验收标准：

- 上传文档后可以看到处理状态。
- L3 叶子块写入 Milvus。
- L1/L2 父块可通过 chunk id 回溯。

### Phase 3：Hybrid Search 与可观测 RAG

交付物：

- Milvus 2.5+ Dense + BM25 Sparse Hybrid Search。
- RRF 排序。
- Jina Rerank 接入。
- 检索评分、重写策略、来源展示。
- Hybrid 失败时自动降级 Dense。

验收标准：

- 同一问题可以看到 dense、sparse、rrf、rerank 的过程记录。
- 结果来源可展开查看 chunk、文档名、分数。
- 关闭或破坏 sparse 能力时系统仍能回答并记录降级。

### Phase 4：高级 RAG 图流程

交付物：

- LLM 问题复杂度分类。
- 简单问题直接检索。
- 复杂问题拆解为 2-4 个子问题。
- 并行 rewritten query 检索，并在 trace 中标记 `sub_agent_1/2/3`。
- Synthesis 节点去重合成。
- Corrective RAG：相关性评分、step_back、hyde、complex 重写策略。
- 会话摘要记忆。

验收标准：

- 多跳问题会生成并行子任务。
- 低相关检索会触发二次重写检索。
- 长会话能生成摘要并注入后续回答上下文。

## 当前继续方式

新会话开始时，先阅读：

1. `PROCESS.md`
2. `ARCHITECTURE.md`
3. `AGENTS.md`
4. 当前代码中的 `apps/web` 与 `apps/api`

然后从 `PROCESS.md` 的“下一步”继续，不要重新解释需求或改换架构，除非用户明确要求。
