# nebulai bot 企业级 RAG 优化路线

日期：2026-06-30

## 当前定位

`nebulai bot` 当前已经不是普通 RAG Demo，而是一个具备企业级 RAG 核心能力的私有知识库问答系统原型。

已具备能力包括：

- 多格式文档 ingestion：`txt / md / docx / pdf / csv / xlsx`
- 三级分块：L1 / L2 / L3 父子 chunk 结构
- Milvus Dense + BM25 Sparse Hybrid Search
- RRF 多路召回融合
- Rerank 精排
- LangGraph RAG 编排
- Corrective RAG
- SSE 流式回答
- 停止生成
- 多轮会话记忆
- RAG Trace 可观测
- Provider fallback / degraded trace
- 检索 eval 基础指标

更准确的简历表述：

> 一个具备企业级 RAG 核心能力的私有知识库问答系统原型，覆盖文档 ingestion、混合检索、纠错 RAG、流式回答、可观测 trace、会话记忆和检索评估，并针对 provider 失败、向量库异常和多格式文档解析做了工程化降级处理。

## 当前还不应过度包装的点

项目可以放简历，但不建议直接描述为“完整企业级 RAG 平台”。

更稳妥的定位是：

- 企业级 RAG 原型
- 私有知识库问答工作台
- 面向企业级能力演进的 RAG 平台雏形

原因是当前还缺少权限治理、生产级文档处理、完整评估闭环、运维监控、安全合规等能力。

## 企业级能力缺口

### 1. 权限与租户隔离

企业级 RAG 首先要解决“谁能看什么”。

当前缺口：

- 用户登录与鉴权
- 多租户 workspace
- 文档级权限
- chunk / source 返回前的权限过滤
- 查询、上传、删除、重命名等操作审计日志

建议目标：

- 支持 user / workspace / document 三层权限模型
- 检索前按 workspace 过滤候选文档
- 检索后返回 source 前再次做权限校验
- 记录用户操作审计日志

验收标准：

- 不同 workspace 的文档互不可见
- 普通用户不能检索未授权文档 chunk
- source 引用不会泄露无权限文档标题或内容
- 管理端可以查看上传、查询、删除等审计记录

### 2. 企业级文档处理

当前已经支持多格式解析，但企业文档通常更复杂。

当前缺口：

- OCR：扫描 PDF、图片合同、盖章文件
- 复杂 PDF layout：双栏、页眉页脚噪声、脚注、跨页段落
- 复杂表格：合并单元格、跨页表格、嵌套表格
- 文档版本管理
- 同名文件增量更新
- ingestion worker 独立部署
- failed job dead-letter queue

建议目标：

- 引入 OCR pipeline
- 引入 PDF layout parser 和 table parser
- 为文档维护版本号和 hash
- 支持文档重新上传后的增量 re-index
- 将 ingestion queue 从 API 进程中拆出为独立 worker

验收标准：

- 扫描 PDF 可以通过 OCR 抽取正文
- PDF 表格可以进入 chunk，并保留页码、表格编号、行列信息
- DOCX / XLSX 表格可以保留表头、行号、列名
- 文档重复上传时可以识别版本变化
- ingestion 失败后进入 dead-letter queue，可手动重试

### 3. 检索质量评估闭环

当前已有 JSONL evalset 和 Recall / MRR / nDCG 指标，但还偏基础。

当前缺口：

- 稳定 golden dataset
- 查询类型分层评估
- answer faithfulness 评估
- citation accuracy 评估
- bad case 收集
- 每次策略调整后的指标对比
- 可视化 eval dashboard

建议目标：

- 建立真实业务文档 evalset
- 覆盖事实型、多跳型、摘要型、对比型问题
- 将每次检索结果、答案、source、指标落库
- 在前端增加 Eval 面板

验收标准：

- 每个 eval case 有稳定 `gold_document_ids` 或 `gold_chunk_ids`
- 可以输出 Recall@k、Precision@k、HitRate@k、MRR、nDCG@k
- 可以标记 bad case 并回流 evalset
- 改动 chunking / retrieval / rerank / prompt 后，可以对比前后指标

### 4. 答案可信度与引用校验

企业 RAG 最怕生成看似合理但无依据的答案。

当前缺口：

- 句级引用校验
- 来源与结论一致性检查
- 多来源冲突检测
- 无依据拒答策略增强
- answer grounding score
- verifier / critic 节点

建议目标：

- 在 Synthesis 后增加 citation verifier
- 校验每个引用编号是否真的支撑对应句子
- 对互相冲突的来源给出冲突提示
- 对低置信度答案要求模型拒答或转为不确定表述

验收标准：

- 答案中的每个 `[1] / [2]` 引用都能对应到 source
- 无 source 时必须明确说明知识库依据不足
- source 与答案结论冲突时，答案必须提示冲突
- trace 中可以看到 grounding / verifier 结果

### 5. 生产级可观测性

当前已有 RAG Trace，但还可以进一步产品化和运维化。

当前缺口：

- embedding / retrieval / rerank / LLM 分阶段耗时
- token 用量统计
- provider 成功率 / 失败率
- ingestion job 指标
- Prometheus / OpenTelemetry
- 错误告警
- admin dashboard

建议目标：

- 为每个 RAG run 记录耗时、token、provider、错误类型
- 将 metrics 暴露为 Prometheus 格式
- 前端增加只看 warning / degraded 的 trace 过滤
- 增加运行状态 dashboard

验收标准：

- 可以看到每次问答的阶段耗时
- 可以统计每日请求量、失败率、平均延迟
- provider 异常可被快速定位
- ingestion 队列积压可见

### 6. 数据治理与运维能力

企业项目需要长期稳定运行。

当前缺口：

- DB migration
- Milvus collection migration
- embedding 维度切换保护
- 数据备份与恢复
- 向量索引重建工具
- 环境 doctor 命令
- CI/CD

建议目标：

- 引入迁移工具管理 PostgreSQL schema
- 增加 Milvus rebuild 命令
- 增加 provider / DB / Redis / Milvus readiness doctor
- 增加 CI 流程：test、lint、typecheck、build

验收标准：

- schema 变化可通过 migration 升级
- embedding 维度变化时系统能明确阻止错误写入
- 可以一键重建 Milvus collection 并重新索引
- CI 能在合并前发现核心问题

### 7. 安全与合规

私有知识库系统必须考虑数据安全。

当前缺口：

- 文件大小限制
- 文件类型安全校验
- 敏感信息脱敏
- prompt injection 防护
- 文档内容注入攻击防护
- API 限流
- provider key 管理

建议目标：

- 上传前校验文件大小、类型和扩展名
- 对文档内容进行敏感信息检测
- 对检索到的 chunk 做 prompt injection 风险扫描
- 增加 API rate limit
- provider key 不在前端暴露

验收标准：

- 超大文件上传会被拒绝并给出明确错误
- 非法文件类型无法进入 ingestion
- 文档中的恶意 prompt 不会直接污染系统指令
- 请求过频会触发限流

### 8. 企业工作台体验

当前 UI 已经是工作台形态，但还可以更像完整平台。

当前缺口：

- 知识库管理页
- 文档详情页
- chunk 预览
- indexing 状态追踪
- Eval 结果页
- Provider 配置页
- 管理员页面

建议目标：

- 将右侧 Knowledge 面板扩展为独立知识库管理视图
- 支持查看文档 chunks、索引状态、失败原因
- 支持查看 eval 历史结果
- 支持 provider live check 和配置状态展示

验收标准：

- 用户可以查看每个文档的 chunk 列表
- 用户可以看到每个文档是否已向量化
- 用户可以对失败文档执行 retry
- 用户可以查看最近 eval 指标和 bad case

## 推荐开发优先级

### P0：让项目更像企业级 RAG，而不是 Demo

1. 独立 ingestion worker
2. dead-letter queue
3. 文档版本管理
4. Milvus rebuild / doctor 命令
5. 真实 evalset 扩充

验收标准：

- API 与 ingestion worker 可以独立启动
- ingestion 失败任务可见、可重试
- 文档重复上传能识别版本
- 本地可以一键检查 DB / Redis / Milvus / Provider 状态
- evalset 至少覆盖 20 个真实问题

### P1：提升复杂文档处理能力

1. PDF OCR
2. PDF layout 解析增强
3. 跨页表格处理
4. DOCX / XLSX 复杂表格增强
5. chunk metadata 增强：页码、sheet、row、column、section

验收标准：

- 扫描 PDF 能抽取正文
- 表格内容可被检索并引用
- source 能展示页码、sheet、行号等定位信息

### P2：提升答案可信度

1. citation verifier
2. answer grounding score
3. source conflict detection
4. no-evidence refusal policy
5. verifier trace 可视化

验收标准：

- 每条引用都能被校验
- 无依据问题不会编造答案
- 冲突来源会被提示
- trace 能显示 verifier 结果

### P3：补齐权限和租户模型

1. 登录鉴权
2. workspace
3. document ACL
4. retrieval 权限过滤
5. audit log

验收标准：

- 用户只能看到自己 workspace 的文档
- 无权限文档不会进入检索结果
- 所有关键操作有审计记录

### P4：生产可观测与管理后台

1. RAG run metrics
2. provider success rate
3. token usage
4. ingestion queue dashboard
5. eval dashboard

验收标准：

- 可以查看系统延迟、失败率、token 消耗
- 可以定位 provider 异常
- 可以查看 ingestion 队列积压
- 可以比较 eval 指标变化

## 简历表达建议

### 不建议写法

- “实现了一个 RAG 问答系统”
- “完成前端页面和接口对接”
- “优化 prompt，提高回答准确率”

这些描述过于普通，无法体现难点。

### 建议写法

可以围绕以下关键词组织：

- Hybrid Search
- LangGraph
- Corrective RAG
- SSE 流式输出
- 可观测 Trace
- 多格式文档解析
- 父子 chunk 回溯
- Provider 降级容错
- RAG Eval
- 文档 ingestion 队列

示例：

> 设计并实现私有知识库 RAG 问答工作台，基于 FastAPI、LangGraph、Milvus、PostgreSQL 和 Redis 构建文档 ingestion、混合检索、纠错 RAG、流式回答、会话记忆和可观测 trace 能力；支持多格式文档解析、Dense + BM25 Sparse Hybrid Search、RRF 融合、Rerank 精排、父子 chunk 上下文回溯和 provider 降级容错，并建立检索评估基线用于持续优化召回质量。

## 最小可展示成果

如果用于简历或面试展示，建议至少准备以下内容：

1. 一段真实文档上传演示
2. 一个复杂问题触发 LangGraph 子问题拆解
3. 一次 Hybrid Search + Rerank 的 trace 展示
4. 一个 provider 失败后的 degraded fallback 展示
5. 一份 eval 指标输出
6. 一个无依据问题的拒答示例
7. 一个 source 引用跳转示例

## 最终判断

当前项目适合放简历，但定位应是：

> 具备企业级 RAG 核心能力的私有知识库问答系统原型。

如果继续补齐 OCR、权限、eval、引用校验、独立 worker 和可观测 metrics，就可以逐步升级为：

> 面向企业内部知识库场景的 RAG 平台。
