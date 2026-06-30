# RAG 知识体系与 nebulai bot 需求完成度梳理

日期：2026-06-30

本文分为两部分：

1. RAG 常见类型、评估测试方法和核心知识点。
2. 对照根目录 `design.md` 的“要点”检查当前 `nebulai bot` 是否已经实现，并列出未完成内容的补齐计划。

## 1. 常见 RAG 类型

RAG（Retrieval-Augmented Generation）不是一种固定架构，而是一组“先检索、再生成、可追溯”的系统设计模式。实际项目通常会混合多种 RAG 类型。

| 类型 | 核心做法 | 特点 | 适用场景 | 常见风险 |
| --- | --- | --- | --- | --- |
| Embedding / Vector RAG | 将文档切块后向量化，查询也向量化，通过向量相似度召回 chunk | 语义召回能力强，能匹配不同表述 | FAQ、制度文档、知识库问答、客服 | 对专有名词、编号、精确关键词不稳定；embedding 维度与索引必须一致 |
| Keyword / BM25 RAG | 用关键词倒排索引或 BM25 召回文本 | 精确词匹配好，解释性强 | 法条、合同、产品型号、错误码、专有名词 | 语义泛化弱，用户换一种说法可能召回不到 |
| Hybrid RAG | 同时使用 dense embedding 和 sparse / BM25，再融合排序 | 兼顾语义召回与关键词召回，是生产系统常见默认方案 | 私有知识库、企业搜索、技术文档问答 | 融合权重、排序策略、降级路径需要可观测 |
| Parent-child / Hierarchical RAG | L1/L2/L3 分层切块，检索小块，生成时回溯父块 | 召回粒度细，同时保留上下文完整性 | 长文档、PDF、合同、政策制度 | 父子关系、chunk id、上下文回溯要稳定 |
| Graph RAG | 抽取实体、关系、事件，构建知识图谱，再结合图检索和文本检索 | 擅长多跳关系、实体关联、全局总结 | 人物/组织关系、供应链、知识图谱、跨文档推理 | 图谱构建成本高；实体消歧、关系质量和增量更新复杂 |
| Agentic RAG | 由 agent 规划检索步骤，可多轮查询、调用工具、反思和重试 | 适合复杂任务，能动态拆解问题 | 多跳问题、研究助手、数据分析、复杂业务流程 | 延迟和成本高；可控性、循环退出和 trace 必须做好 |
| Corrective RAG / CRAG | 检索后判断相关性，低相关时改写问题或二次检索 | 能减少“低质量召回直接生成”的问题 | 私有文档质量参差、用户问题模糊 | 评分器自身可能误判；需要记录重写原因和结果 |
| Multi-query RAG | 为同一问题生成多个查询并行检索，再合并去重 | 提升召回覆盖面 | 用户问题长、表达复杂、有多个子意图 | 容易引入噪声，需要 rerank 和去重 |
| HyDE RAG | 先让模型生成一个假设答案/假设文档，再用它检索 | 无结果或表达抽象时能改善召回 | 抽象问题、概念解释、语义跨度大 | 假设内容可能偏离事实，必须只把它用于检索，不可当事实 |
| Self-RAG | 模型在生成中自评是否需要检索、是否有证据支持 | 让生成和检索更自适应 | 长回答、开放式问答 | 实现复杂，评价和控制难 |
| Rerank RAG | 初召回后用 cross-encoder / rerank API 重新排序 | 通常显著改善 top-k 质量 | top-k 候选较多、答案依赖前几条来源 | 额外延迟和成本；rerank 失败要保留原始顺序 |
| Memory RAG | 把会话摘要、用户画像、历史偏好作为可检索或可注入上下文 | 支持多轮问答和长期上下文 | 助手、客服、个人知识库 | 旧摘要污染新问题；需要摘要更新策略和隐私边界 |
| Multimodal RAG | 对图片、表格、音频、视频等做 OCR/解析/向量化 | 能覆盖非纯文本知识 | PPT、扫描件、报表、图文知识库 | 解析质量决定上限；证据引用更复杂 |

## 2. RAG 评估和测试怎么做

RAG 评估要拆成四层：数据层、检索层、生成层、系统层。不要只看“模型回答像不像”，否则很难定位问题是切块、索引、召回、排序、prompt 还是模型本身。

### 2.1 数据集准备

建议建立一个可版本化的 eval set：

- `question`：用户问题。
- `expected_answer`：标准答案或答案要点。
- `gold_document_ids`：应命中的文档 id。
- `gold_chunk_ids`：应命中的 chunk id，越细越能测召回。
- `must_cite`：答案必须引用的来源。
- `answer_type`：事实型、列表型、比较型、多跳型、摘要型、拒答型。
- `difficulty`：simple / medium / complex。
- `tags`：业务域、文档类型、是否需要表格、是否需要多跳。

评估集来源：

- 从真实用户问题抽样。
- 从文档标题、目录、关键条款人工构造。
- 用 LLM 生成候选问题，再人工审核。
- 把线上失败 case 固化为回归测试。

### 2.2 检索层指标

检索层的目标是回答：“该找的证据有没有找回来，排名是否靠前？”

| 指标 | 含义 | 适用判断 |
| --- | --- | --- |
| Recall@k | 前 k 条结果里是否包含 gold chunk / gold doc | 最重要的 RAG 检索指标；召回不到就很难答对 |
| Precision@k | 前 k 条结果中相关结果占比 | 衡量噪声；低 precision 会污染生成 |
| Hit Rate@k | 前 k 条是否至少命中一个相关结果 | 适合问答场景的粗粒度通过率 |
| MRR | 第一个相关结果排名越靠前分越高 | 衡量 top result 质量 |
| nDCG@k | 相关性分级排序质量 | 适合 gold relevance 有 0/1/2/3 多档标注 |
| Context Precision | 被放入 prompt 的上下文中，真正有用的比例 | 检查是否塞了太多无关 chunk |
| Context Recall | 标准答案所需证据是否被上下文覆盖 | 检查生成前证据是否足够 |

建议门槛：

- 早期：`Hit Rate@5`、`Recall@5` 先达标。
- 进入真实业务前：补 `MRR`、`nDCG@10`、`Context Precision`。
- 对合同/政策类系统：必须单独测编号、条款、日期、金额、专有名词的关键词召回。

### 2.3 生成层指标

生成层的目标是回答：“基于已给证据，模型有没有答对、有没有编造？”

| 指标 | 含义 | 测试方式 |
| --- | --- | --- |
| Answer Correctness | 答案是否覆盖标准答案要点 | 人工打分或 LLM-as-judge |
| Faithfulness / Groundedness | 答案是否能被引用来源支持 | LLM judge、NLI 模型、人工抽检 |
| Citation Accuracy | 引用编号是否真的支持对应句子 | 人工或自动对齐 source chunk |
| Completeness | 是否遗漏关键条件、例外、步骤 | rubric 评分 |
| Refusal Accuracy | 无证据时是否明确拒答或说明不足 | 构造无答案问题 |
| Conciseness | 是否啰嗦、重复、偏离问题 | rubric 评分 |

注意：LLM-as-judge 不是绝对真值，建议用于批量趋势分析；关键业务场景仍需要人工抽检。

### 2.4 系统层指标

系统层衡量“能不能稳定上线”：

- 首 token 延迟、总响应时长、SSE 断流率。
- 检索耗时、embedding 耗时、rerank 耗时、LLM 耗时。
- provider 失败率、降级率、重试率。
- ingestion 成功率、解析失败率、向量写入失败率。
- 每个问题的 token 成本、rerank 成本、embedding 成本。
- trace 完整率：每次回答是否都有 run、step、source、warning、done。

### 2.5 LangSmith 和其他技术路线

LangSmith 是 LangChain / LangGraph 生态里常见的观测和评估平台，适合 trace、dataset、prompt/version、LLM-as-judge 和线上调试。但它不是唯一选择。

| 路线 | 代表工具 | 适合什么 | 特点 |
| --- | --- | --- | --- |
| LangChain 生态 | LangSmith | LangGraph/LangChain 项目 trace 和 eval | 集成顺滑，适合链路级调试 |
| 开源 RAG 评估 | Ragas | 评估 context precision/recall、faithfulness、answer relevancy | RAG 指标更直接，可离线跑 |
| LLM 应用测试 | DeepEval | 单测式 eval、LLM judge、回归测试 | 适合接入 CI |
| 可观测与反馈 | TruLens | Groundedness、feedback functions、链路观测 | 强调应用级 feedback |
| Prompt/模型回归 | promptfoo | prompt、模型、参数 A/B 测试 | 配置化，适合快速比较 |
| LLM Observability | Arize Phoenix / OpenInference | trace、embedding 可视化、检索调试 | 开源可观测路线 |
| 自建评估 | pytest + JSONL eval set + PostgreSQL trace | 项目强定制、私有化部署 | 成本低，可控性强，但要自己维护 |
| 传统 IR 评估 | pytrec_eval / trec_eval | 检索排序指标 | 适合严格测 Recall/MRR/nDCG |
| 人工审核平台 | Label Studio / 自建标注页 | 高价值业务答案审核 | 最可靠，但成本高 |

本项目建议路线：

1. 先自建 `evalset.jsonl`，用 pytest 跑检索层 `Recall@k / MRR / nDCG`。
2. 再接 Ragas 或 DeepEval 做生成层 `faithfulness / answer correctness`。
3. 如果继续深度使用 LangGraph，再接 LangSmith 做 trace、dataset 和回归评估。
4. 线上阶段把 PostgreSQL `rag_runs / rag_steps / rag_sources` 作为内部观测数据源，补一个 eval runner，把失败问题固化为回归集。

## 3. RAG 常见知识点

### 3.1 Chunking

Chunking 是把文档切成可检索片段。切太大，召回不准；切太小，上下文不完整。

常见策略：

- 固定长度切块：实现简单，但容易切断语义。
- 按标题/段落切块：更自然，适合 Markdown、制度文档。
- 滑窗切块：保留 overlap，减少边界信息丢失。
- 层级切块：L1/L2/L3，检索叶子块，生成时回溯父块。

### 3.2 Embedding

Embedding 是把文本映射为向量。向量距离越近，语义越相似。

关键点：

- embedding 模型、维度、向量库 collection schema 必须一致。
- 更换 embedding 模型通常需要重建索引。
- 中文、英文、代码、法律文本可能适合不同 embedding 模型。

### 3.3 向量数据库

向量数据库用于存储向量并做近似最近邻搜索。常见选型包括 Milvus、Qdrant、Weaviate、Pinecone、Elasticsearch/OpenSearch vector、pgvector。

核心概念：

- collection / index / metric。
- dense vector / sparse vector。
- metadata filter。
- upsert / delete / rebuild。
- ANN 索引和召回精度/速度权衡。

### 3.4 BM25 和 Sparse Retrieval

BM25 是经典关键词检索算法，基于词频、逆文档频率和文档长度归一化。它适合精确词、编号、专有名词、条款检索。

Sparse retrieval 可以是 BM25，也可以是 SPLADE 等稀疏向量模型。

### 3.5 Hybrid Search

Hybrid Search 同时使用 dense 和 sparse 检索。常见做法：

- dense top-k + sparse top-k。
- 分数归一化后加权融合。
- RRF 融合。
- 先扩大召回，再 rerank。

### 3.6 RRF

RRF（Reciprocal Rank Fusion）是一种按排名融合多个结果列表的方法。它不强依赖不同检索器的原始分数可比性，适合融合 BM25 和向量检索结果。

直观公式：

```text
score(d) = sum(1 / (k + rank_i(d)))
```

文档在多个检索列表中排名都靠前时，融合分数更高。

### 3.7 Rerank

Rerank 是对初召回候选进行二次排序。常见 reranker 是 cross-encoder，它会同时看 query 和 passage，比单独向量相似度更精细。

典型流程：

1. 初召回 20-100 条。
2. rerank 打分。
3. 取 top 3-10 条进入 prompt。

### 3.8 Query Rewrite

Query rewrite 是改写用户问题来改善召回。

常见策略：

- step_back：抽象到上位背景和定义。
- HyDE：生成假设答案再检索。
- multi-query：生成多个不同角度查询。
- decomposition：把复杂问题拆成多个子问题。

### 3.9 Corrective RAG

Corrective RAG 在初次检索后评估相关性。如果证据不足，则触发 query rewrite、二次检索或拒答。

关键是 trace 必须记录：

- 初次召回结果。
- 评分器判断。
- 是否重写。
- 重写策略。
- 二次检索来源。
- 最终进入生成的证据。

### 3.10 Agentic RAG

Agentic RAG 让 agent 自主规划检索步骤、调用工具、反思结果。它比普通 RAG 强，但也更难控。

生产系统要限制：

- 最大轮数。
- 最大工具调用次数。
- 超时。
- 成本预算。
- 可解释 trace。
- 失败降级。

### 3.11 Graph RAG

Graph RAG 通常包含：

- 文档实体抽取。
- 关系抽取。
- 社区发现或图聚类。
- 局部图检索和全局摘要。
- 图证据 + 文本证据合成。

它适合多实体、多关系、多跳推理，不适合一开始就作为所有知识库的默认方案。

### 3.12 Synthesis

Synthesis 是把多条证据合成为最终答案。高级 synthesis 不只是“把 source 塞给 LLM”，还应包括：

- 来源去重。
- 冲突检测。
- 证据分组。
- 引用编号绑定。
- 无证据拒答。
- 答案结构化。

## 4. 当前项目对照 `design.md` 的完成度

结论：当前项目已经实现了可运行的私有知识库 RAG 主链路，包括前端工作台、FastAPI SSE、文档 ingestion、三级分块、L3 leaf-only 向量化、Milvus Dense + BM25 Hybrid Search、RRF、rerank、Corrective RAG、会话摘要、trace 恢复、event queue、Send API 子任务和基础 Auto-merging。`design.md` 中仍需注意的边界主要是：

- 并未使用 `agent.astream(stream_mode="messages")` 作为 token 流主路径，而是 FastAPI SSE 直接封装 provider token stream。
- 实时 RAG 过程可视化已经从批量组装 step 升级为 workflow event queue，节点执行时可推送 question/retrieval/rewrite/sub-agent/rerank/synthesis step。
- 复杂问题分解已有 question planner、子问题拆解、LangGraph `Send API` fan-out/fan-in 和 sub-agent 完整检索链路。

### 4.1 要点完成度表

| design.md 要点 | 当前状态 | 依据 | 需要补齐 |
| --- | --- | --- | --- |
| 1. 混合检索：稠密向量 + BM25 稀疏向量，Milvus Hybrid Search + RRF | 已实现 | `retrieval.py` 使用 `AnnSearchRequest` dense + sparse，`RRFRanker()`；`milvus.py` 使用 BM25 Function | 后续可补 eval 指标证明 hybrid 比 dense 单路更好 |
| 2. 流式输出：后端 `agent.astream(stream_mode="messages")` 逐 token，前端 SSE + ReadableStream | 部分实现 | 前后端 SSE/token streaming 已有；但不是 `agent.astream(stream_mode="messages")` 主路径 | 如强依赖 LangGraph token stream，需要把 provider streaming 接入 LangGraph `astream` 或在图节点中透传 message stream |
| 3. 回答终止：AbortController + StreamingResponse 中断 | 已实现 | 前端 `AbortController` + `/api/chat/runs/{run_id}/cancel`；后端 run control 和 disconnect 检查 | 可补取消后的资源释放压测 |
| 4. 实时 RAG 过程可视化：思考阶段展示，通过 `asyncio.Queue + 后台任务` | 已实现基础版 | `run_rag_stream()` 后台运行 workflow task，并消费节点写入的 `event_queue`；节点执行时即时 emit step | 后续可补更细粒度 running/progress 事件 |
| 5. RAG 过程可观测：记录检索、评分、重写、来源 | 已实现 | PostgreSQL `rag_runs / rag_steps / rag_sources`，前端 RAG Trace | 可补 trace 导出和失败 case 标注 |
| 6. 会话摘要记忆：自动摘要旧消息并注入系统提示 | 已实现基础版 | `sessions.summary` 已有；`build_session_summary_with_llm()` 支持真实 LLM 摘要，无 key 时 deterministic fallback | 后续补摘要质量 eval 和前端摘要 inspector |
| 7. Milvus 2.5+ 原生 BM25 Function | 已实现 | `milvus.py` schema 对 `text` 字段启用 analyzer，并添加 `FunctionType.BM25` 输出 `sparse_vector` | 可补 collection migration 脚本 |
| 8. 自适应问题分解与并行 Sub-Agent 图流程，LangGraph Send API，Synthesis 去重合成 | 已实现基础版 | 已有 deterministic/LLM question planner、子问题拆解、LangGraph `Send API` fan-out/fan-in、sub-agent 完整链路、基础 synthesis 去重和引用绑定 | 后续补更细粒度子任务 UI 和质量评估 |
| 9. Corrective RAG、多策略自适应重写、Jina Rerank | 大部分实现 | `corrective.py` 支持 deterministic/LLM grader、`step_back/hyde/complex`；`rerank.py` 支持通用 `RERANK_*` 并兼容 `JINA_*` | 当前相关性判断不是严格 Yes/No schema；可补结构化 evaluator 和更细阈值 |
| 10. 双向降级：Hybrid 失败降级 Dense | 已实现 | `retrieve_sources()` hybrid 失败后 `_dense_search()`，两者失败时返回 `retrieval_failed` 空来源 | 可补 sparse-only fallback 或 keyword-only fallback |
| 11. 三级分块 + Auto-merging | 已实现基础版 | `chunking.py` 生成 L1/L2/L3；检索 L3 后回溯 L2；多个 L2 命中同一 L1 时自动提升到 L1 上下文 | 后续补 token budget aware packing |
| 12. Leaf-only 向量化，父块写 DocStore | 已实现 | `milvus.py` 只索引 L3；PostgreSQL chunks 保存父子关系 | 可补父块版本和重建索引工具 |

### 4.2 未完成内容补齐计划

#### P0：补 RAG 评估闭环

当前缺口不是主链路不可运行，而是缺少系统化 RAG eval。

交付物：

- `apps/api/evals/rag_evalset.jsonl`
- `apps/api/src/nebulai/evals/retrieval_eval.py`
- 检索指标：`HitRate@k`、`Recall@k`、`MRR`、`nDCG@k`
- 生成指标：先接 LLM-as-judge rubric，后续可接 Ragas / DeepEval

验收标准：

- 能对同一批问题比较 dense、hybrid、hybrid+rerank。
- 每次改 chunking/retrieval/rerank 后能看到指标变化。
- 失败样本能回写为回归 case。

#### P1：补真正的实时 RAG event queue

当前已完成基础版：workflow 后台执行，节点执行时向 event queue 写入 step，SSE 循环实时消费。

交付物：

- RAG workflow event emitter。
- 节点执行时即时发送 `question_analysis/retrieval/rewrite/rerank/source`。
- 后端 SSE 从 queue 消费事件，answer token 与 RAG step 共用一条 stream。

验收标准：

- Milvus 检索较慢时，前端能先看到“开始检索/正在检索”。
- rewrite 和二次检索一发生就进入 trace。
- 取消生成时 queue、workflow、provider stream 都能停止。

#### P2：补完整复杂问题分解和 LangGraph Send API

当前已完成基础版：question planner 会拆解复杂问题，LangGraph 通过 `Send API` fan-out 到 sub-agent，每个 sub-agent 执行 retrieve -> corrective -> optional secondary retrieval -> rerank，再 fan-in 回主链路。

交付物：

- LLM complexity classifier：输出 `simple | multi_hop | comparison | broad_summary`。
- LLM decomposition：复杂问题拆成 2-4 个子问题。
- LangGraph `Send` 并行子图，每个子问题完整执行 retrieve -> corrective -> rerank。
- 子任务 trace：记录 parent run、sub run、query、sources、score。

验收标准：

- 多跳问题能看到明确子问题。
- 每个子问题有独立检索证据。
- 子任务失败不阻断其他子任务，并在 trace 中降级。

#### P3：补独立 Synthesis 节点

当前已经有基础 synthesis 节点，能做证据去重、无证据策略和引用编号要求；后续还需要继续补冲突检测、句级引用校验和 token 预算压缩。

交付物：

- source grouping：按文档、子问题、chunk 层级分组。
- evidence dedupe：去重相同 parent chunk。
- conflict detection：同一问题多个来源冲突时提示。
- citation binding：答案句子与 source 编号绑定。
- no-evidence policy：来源不足时拒答或说明不足。

验收标准：

- 回答中的 `[1]`、`[2]` 能稳定对应支撑句。
- 多来源冲突时不直接混合成一个确定结论。
- 无来源问题不会伪造知识库答案。

#### P4：补真正摘要记忆

当前已完成基础版：有真实 LLM key 时使用 LLM 生成结构化摘要，无 key 或失败时回退规则式摘要。

交付物：

- LLM summary provider。
- 触发条件：消息数、token 估算或 session 长度。
- 摘要结构：用户目标、已确认事实、待办、约束、最近问题。
- 摘要 eval：检查是否保留关键事实、是否引入幻觉。

验收标准：

- 长会话后 prompt 不爆 token。
- 后续问题能利用历史摘要。
- 摘要内容可在 trace 或 session inspector 中查看。

#### P5：补 Auto-merging 策略

当前已完成基础版：单个 L3 命中回溯 L2，多个 L2 命中同一 L1 时自动提升到 L1 上下文。

交付物：

- L3 相邻 chunk 命中计数。
- 同一 L2 下命中超过阈值时合并 L2。
- 同一 L1 下多个 L2 命中时合并 L1 摘要或 L1 原文。
- prompt budget aware context packing。

验收标准：

- 对长条款问题，能自动提升到父块上下文。
- 对短事实问题，仍只使用小块，避免上下文污染。

## 5. 建议的下一步

如果优先级按“对项目质量提升最大”排序，建议：

1. 先做 `P0 RAG eval`，否则后续调 chunking、rerank、graph 都没有量化依据。当前已落地基础版：`apps/api/evals/rag_evalset.jsonl`、`nebulai.evals.retrieval_eval`、`pnpm --filter @nebulai/api eval:retrieval`。
2. 扩充真实稳定 gold case 后，继续增强 `P3 Synthesis 节点`。当前基础版已接入 source 去重、无证据策略和引用编号要求；后续还要补冲突检测、句级引用校验和 prompt budget packing。
3. 在真实 provider 下复测 LLM planner、LLM summary、rerank 和引用质量，把失败样本写回 evalset。
4. 继续补深层质量项：synthesis 冲突检测、句级引用校验、prompt budget packing、多实例 ingestion worker。

短期最小闭环：

```text
evalset.jsonl -> retrieval eval -> synthesis policy -> 回归测试 -> PROCESS.md 记录指标
```

这条线比继续堆更多 RAG 技巧更重要，因为它能告诉我们每次改动到底让系统变好了还是变差了。
