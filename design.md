## 技术栈
1. 项目前端使用tanstack start + taiwind css + ts
2. ui框架使用：assistant-ui
3. rag相关，你可以使用python+langchain/langGraph来实现
4. 后端我的选型是nest.js/FastAPI(你觉得哪一个合适就用哪一个) + PostgreSQL + Redis
5. 向量数据库Milvus

## 架构
可以将项目设计成pnpm monorepo，这样可以更清晰划分目录

## 要点
参考仓库：https://github.com/icey1287/SuperMew
1. 混合检索落地：稠密向量 + BM25 稀疏向量，Milvus Hybrid Search + RRF 排序，兼顾语义与词匹配
2. 流式输出（Streaming）：后端基于 agent.astream(stream_mode="messages") 逐 token 推送，前端 SSE + ReadableStream 实现打字机效果
3. 回答终止功能：前端 AbortController + 后端 StreamingResponse 支持用户随时中断正在生成的回答
4. 实时 RAG 过程可视化：检索过程在模型"思考中"阶段就开始展示，通过 asyncio.Queue + 后台任务架构实现工具执行期间的实时推送。
5. RAG 过程可观测：记录检索、评分、重写与来源信息，前端可展开查看每一步细节
6. 会话摘要记忆：自动摘要旧消息并注入系统提示，维持上下文且控制 token。
7. Milvus 2.5+ 原生 BM25 混合检索：彻底摒弃本地客户端手写 BM25 序列化和统计同步的繁琐设计。通过在 Milvus 集合 schema 中为 text 字段绑定 FunctionType.BM25 计算函数，由向量数据库在服务端原生提取稀疏特征，保证高效率的 Dense + Sparse 混合检索与完美的统计对齐
8. 自适应问题分解与并行 Sub-Agent 图流程：主图利用 LLM 分类器自动研判提问复杂度。简单问题直接检索；复杂问题通过 LLM 拆解为 2-4 个独立子问题，利用 LangGraph 的 Send API 并行启动子 Agent 完整流程，最终在 Synthesis 节点进行去重合成，解决多跳跨域召回痛点。
9. 纠错型 RAG（Corrective RAG）与多策略自适应重写：检索后引入结构化评分器，判断文档与问题的相关性（Yes/No）。当评分过低或无结果时，智能重写路由在退步问题扩展（step_back）、假设性文档生成（hyde）和综合扩展（complex）间自适应选择，实施二次重度扩展检索。
Jina Rerank 接入：Hybrid/Dense 召回后进行 API 级精排，支持返回 rerank_score 并在前端可视化。
10. 双向降级：稀疏生成或 Hybrid 调用失败时自动降级为纯稠密检索，提升稳定性
11. 三级分块 + Auto-merging：L1/L2/L3 三层滑窗切分；检索时优先召回 L3，满足阈值后自动合并到父块（L3->L2->L1）。
12. Leaf-only 向量化存储：仅叶子分块写入 Milvus，父块写入 DocStore，减少向量冗余并保留上下文聚合能力。
