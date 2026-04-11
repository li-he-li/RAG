# Phase 1: 基础设施（不改路由，纯后端横切能力）

## 1. 基础设施与依赖

- [x] 1.1 添加新依赖到 requirements.txt：`pyyaml>=6.0`、`tiktoken>=0.7`、`watchfiles>=0.21`
- [x] 1.2 创建目录结构：`backend/app/prompts/`、`backend/app/services/analytics/`
- [x] 1.3 创建 `__init__.py`：`backend/app/prompts/__init__.py`、`backend/app/services/analytics/__init__.py`

## 2. 遥测服务 (Monitorable)

- [x] 2.1 TDD: 编写 `tests/test_telemetry.py` — 测试事件记录、correlation ID 传播、指标收集
- [x] 2.2 实现 `backend/app/services/analytics/telemetry.py` — TelemetryService 单例（结构化 JSON 事件、correlation_id、延迟直方图、token 计数）
- [x] 2.3 实现 `backend/app/services/analytics/middleware.py` — FastAPI 中间件自动注入 correlation ID
- [x] 2.4 运行测试确认通过 → commit: `feat(telemetry): add centralized telemetry service`

## 3. Prompt 注册表 (Updatable)

- [x] 3.1 TDD: 编写 `tests/test_prompt_registry.py` — 测试 YAML 加载、变量替换、版本追踪、请求级 pinning
- [x] 3.2 实现基础 PromptRegistry：`backend/app/prompts/registry.py` — YAML 加载、`{{var}}` 替换、版本号
- [x] 3.3 从现有代码中提取所有 prompt 到 YAML 文件：
  - `backend/app/prompts/similar_case_search.yaml`
  - `backend/app/prompts/contract_review.yaml`
  - `backend/app/prompts/opponent_prediction.yaml`
  - `backend/app/prompts/chat.yaml`
  - `backend/app/prompts/retrieval_explanation.yaml`
- [x] 3.4 实现热加载：使用 watchfiles 监控 prompts 目录，文件变更时自动重新加载模板
- [x] 3.5 实现请求级 prompt version pinning：单次请求生命周期内锁定 resolved prompt versions
- [x] 3.6 将 prompt name/version 快照暴露给后续 trajectory / replay 服务
- [x] 3.7 运行测试确认通过 → commit: `feat(prompts): extract prompts to YAML with hot-reload and version pinning`

## 4. Token 预算系统 (Efficient)

- [x] 4.1 TDD: 编写 `tests/test_token_budget.py` — 测试 token 计数、预算分配、缓存、自适应校准
- [x] 4.2 实现 TokenBudgetManager：`backend/app/services/analytics/token_budget.py` — tiktoken 计数（cl100k_base）、预算分配（system/retrieval_context/generation）、LRU 缓存
- [x] 4.3 安全裕度设为 25%，实现自适应校准：记录 actual vs estimated 比值，偏差 >15% 时自动调整校准系数
- [x] 4.4 集成到 prompt 组装流程：发送前自动估算，超限拒绝并返回 TokenBudgetExceededError
- [x] 4.5 运行测试确认通过 → commit: `feat(token-budget): add token estimation with adaptive calibration`

---

# Phase 2: Agent 框架 + 治理（框架就绪但未接业务域）

## 5. Agent 框架核心 (Effective)

- [x] 5.1 创建目录结构：`backend/app/agents/`、`backend/app/agents/__init__.py`
- [x] 5.2 TDD: 编写 `tests/test_agent_framework.py` — 测试 AgentBase、Pipeline 编排（含简化拓扑）、streaming
- [x] 5.3 实现 AgentBase 抽象类：`backend/app/agents/base.py` — run()、validate()、name 属性
- [x] 5.4 实现 PlannerAgent、ExecutorAgent、ValidatorAgent 抽象
- [x] 5.5 实现 AgentPipeline 编排器：支持三种拓扑 `[Executor]`、`[Executor→Validator]`、`[Planner→Executor→Validator]`，支持 streaming
- [x] 5.6 实现 SkillRegistry：`backend/app/agents/registry.py` — 按 name 注册和发现 agent
- [x] 5.7 运行测试确认通过 → commit: `feat(agents): add agent framework with flexible pipeline topologies`

## 6. LLM 输出治理 (Safe — 输出端)

- [x] 6.1 TDD: 编写 `tests/test_output_governance.py` — 测试安全过滤、注入检测、schema 校验、流式两层策略
- [x] 6.2 实现 OutputGovernancePipeline：`backend/app/agents/output_governance.py`
  - 非流式路径：Validator 之后、JSON 响应之前，做完整治理（PII + schema + 注入）
  - 流式层（per-chunk）：轻量 pattern scan（注入关键词黑名单），可疑时中断并发 `governance_blocked` 事件
  - 聚合层（post-stream）：流结束后对完整输出做全量治理，不通过则发 `governance_retracted` 事件
- [x] 6.3 集成到 AgentPipeline：确保所有输出路径（streaming / sync / error recovery）均经过治理
- [x] 6.4 实现审计日志：记录所有治理决策（pass/block/retract）
- [x] 6.5 运行测试确认通过 → commit: `feat(governance): add output governance with streaming two-layer strategy`

## 7. 工具执行治理 (Safe — 工具端)

- [x] 7.1 TDD: 编写 `tests/test_tool_governance.py` — 测试 allowlist、参数 schema、side-effect 审批策略、审计日志
- [x] 7.2 实现 ToolGovernancePolicy：`backend/app/agents/tool_governance.py`
  - ToolRegistry allowlist：只有注册工具可被调用
  - 参数 schema 校验：无效参数拒绝且无副作用
  - side-effect 分级：read-only 自动放行，stateful tool 需外部审批规则
  - Pre-execution injection defense：检查 tool-bound 输入中的注入尝试
- [x] 7.3 集成到 Planner / Executor 的工具调用入口：任何 tool invocation 都先经过治理层
- [x] 7.4 实现审计日志：每次治理决策（allow/block/approval-required）持久化
- [x] 7.5 运行测试确认通过 → commit: `feat(governance): add non-bypassable tool governance`

## 8. API 兼容适配层 (Compatibility)

- [x] 8.1 TDD: 编写 `tests/test_compatibility_adapter.py` — 覆盖非流式 JSON 响应和流式事件序列的 golden contract
- [x] 8.2 实现 CompatibilityAdapter：`backend/app/agents/compatibility.py` — 将 agent 内部 typed result / 内部事件映射回现有外部 API 契约
- [x] 8.3 确认内部新增事件（plan_created、step_started 等）不会直接泄露给旧前端
- [x] 8.4 运行测试确认通过 → commit: `feat(compat): add API compatibility adapter layer`

## 9. 健壮性保障 (Robust)

- [x] 9.1 TDD: 编写 `tests/test_robustness.py` — 测试幂等重试、优雅取消、async task 泄漏管理
- [x] 9.2 实现幂等重试：基于 session_id + request_hash 去重，重复请求返回缓存结果或忽略
- [x] 9.3 实现优雅取消：前端 AbortSignal / 断开连接时传播到后端 async LLM 调用，及时释放资源
- [x] 9.4 实现 async task 泄漏管理：追踪所有 background task，shutdown 时取消孤儿任务
- [x] 9.5 实现脏状态清理：启动时清理超过 TTL 的孤立临时数据
- [x] 9.6 运行测试确认通过 → commit: `feat(robust): add idempotent retry and graceful cancellation`

## 10. Golden Snapshot Contract Test（Phase 3 前置守护）

- [x] 10.1 对现有 4 个核心端点录制 golden snapshot：`/api/v1/similar-cases/compare`、`/api/v1/contract-review/stream`、`/api/v1/chat/stream`、`/api/v1/prediction/*`
- [x] 10.2 为每个端点建立 legacy contract fixtures（JSON 结构 + streaming 事件序列 + HTTP status codes）
- [x] 10.3 编写 `tests/test_api_contract.py` — 验证端点响应结构与 golden snapshot 一致
- [x] 10.4 运行测试确认通过 → commit: `test(contract): add golden snapshot API contract tests`

---

# Phase 3: 业务域迁移（每迁移一个域即可上线验证）

## 11. 轨迹记录 (Compounding) — 在业务域迁移前就绪，为后续优化积累数据

- [x] 11.1 创建目录结构：`backend/app/services/trajectory/`、`backend/app/services/trajectory/__init__.py`
- [x] 11.2 TDD: 编写 `tests/test_trajectory.py` — 测试轨迹记录、查询、回放、脱敏
- [x] 11.3 创建数据库表：`agent_trajectory` — session_id, agent_name, step_type, input_hash, output, duration_ms, token_usage, prompt_versions
- [x] 11.4 实现 TrajectoryLogger：`backend/app/services/trajectory/logger.py` — 异步写入、不阻塞主流程
- [x] 11.5 实现轨迹数据治理：默认脱敏/hash、全文显式开关、TTL retention cleanup
- [x] 11.6 将 prompt version 快照写入 trajectory 记录，确保 replay 可追溯
- [x] 11.7 集成到 AgentPipeline：每个 agent step 自动记录轨迹
- [x] 11.8 添加查询 API：`GET /api/v1/trajectories/{session_id}`
- [x] 11.9 运行测试确认通过 → commit: `feat(trajectory): add structured trajectory logging with data governance`

## 12. 类案搜索 Agent (Effective)

- [x] 12.1 TDD: 编写 `tests/test_agent_similar_case.py` — 测试执行、验证、API 契约兼容
- [x] 12.2 实现 SimilarCaseExecutor：调用现有 retrieval + similar_case_search 服务（策略选择内联为同步函数，不需要完整 PlannerAgent）
- [x] 12.3 实现 SimilarCaseValidator：调用 traceability 验证 + 溯源校验
- [x] 12.4 组装简化 pipeline：`[Executor → Validator]` 拓扑
- [x] 12.5 修改 search router：`/api/v1/similar-cases/compare` 路由改为通过 agent pipeline + CompatibilityAdapter 调度
- [x] 12.6 运行 golden snapshot contract test 确认 API 响应格式兼容 → commit: `feat(agents): similar-case search agent pipeline`

## 13. 合同审查 Agent (Effective)

- [x] 13.1 TDD: 编写 `tests/test_agent_contract_review.py` — 测试规划、执行、验证、streaming、API 契约兼容
- [x] 13.2 实现 ContractReviewPlanner：条款分割策略、模板匹配
- [x] 13.3 实现 ContractReviewExecutor：差异分析 + LLM 审查（streaming）
- [x] 13.4 实现 ContractReviewValidator：findings 一致性校验
- [x] 13.5 组装全链路 pipeline：`[Planner → Executor → Validator]` 拓扑
- [x] 13.6 修改 search router：`/api/v1/contract-review/stream` 改为通过 agent pipeline + CompatibilityAdapter
- [x] 13.7 运行 golden snapshot contract test 确认 streaming 格式兼容 → commit: `feat(agents): contract review agent pipeline`

## 14. 观点预测 Agent (Effective)

- [x] 14.1 TDD: 编写 `tests/test_agent_opponent_prediction.py` — 测试规划、执行、验证、API 契约兼容
- [x] 14.2 实现 PredictionPlanner：案情画像构建、争议焦点推断
- [x] 14.3 实现 PredictionExecutor：论点生成、证据检索、论点排序
- [x] 14.4 实现 PredictionValidator：报告完整性校验
- [x] 14.5 组装全链路 pipeline：`[Planner → Executor → Validator]` 拓扑
- [x] 14.6 修改 prediction router：路由改为通过 agent pipeline + CompatibilityAdapter
- [x] 14.7 运行 golden snapshot contract test 确认 API 响应格式兼容 → commit: `feat(agents): opponent prediction agent pipeline`

## 15. Chat Agent (Effective)

- [x] 15.1 TDD: 编写 `tests/test_agent_chat.py` — 测试 chat agent pipeline、streaming、API 契约兼容
- [x] 15.2 实现 ChatExecutor：检索 + DeepSeek 流式生成（意图识别内联，不需要完整 PlannerAgent）
- [x] 15.3 实现 ChatValidator：citation 一致性校验
- [x] 15.4 组装简化 pipeline：`[Executor → Validator]` 拓扑
- [x] 15.5 修改 search router：`/api/v1/chat/stream` 改为通过 agent pipeline + CompatibilityAdapter
- [x] 15.6 运行 golden snapshot contract test 确认 streaming 格式兼容 → commit: `feat(agents): chat agent pipeline`

## 16. Phase 3 集成验证

- [x] 16.1 编写端到端集成测试：完整 agent pipeline 从 HTTP 请求到响应，覆盖全部 4 个业务域
- [x] 16.2 验证 7 项企业要求达标状态（Effective/Efficient/Safe/Robust/Monitorable/Updatable/Compounding）
- [x] 16.3 更新审计报告 `docs/代码质量审计报告.md`
- [x] 16.4 更新 `docs/` 下的架构文档
- [x] 16.5 全量测试通过 → commit: `feat(agents): phase 3 complete — all domains migrated`

---

# Phase 4: 优化闭环（延后，需轨迹数据积累 ≥200 条 + 人工 golden set）

## 17. DSPy 集成 (Updatable + Compounding)

- [x] 17.1 添加依赖：`dspy-ai>=2.5`
- [x] 17.2 TDD: 编写 `tests/test_dspy_signatures.py` — 测试 DSPy Signature 加载和输入输出
- [x] 17.3 为每个业务域创建 DSPy Signature：`backend/app/prompts/signatures.py`
- [x] 17.4 创建 DSPy Module 包装器，将 YAML prompt 映射到 DSPy Signature
- [x] 17.5 从 trajectory 表导出评估集，加载到 DSPy Metric
- [x] 17.6 实现优化器配置（BootstrapFewShot），在评估集上验证效果
- [x] 17.7 若 DeepSeek 不支持 DSPy meta-prompt，准备 fallback：手动 few-shot 管理 + A/B prompt 比较
- [x] 17.8 运行测试确认通过 → commit: `feat(dspy): integrate DSPy for prompt optimization`

## 18. 最终验证

- [x] 18.1 验证所有 7 项企业要求完全达标
- [x] 18.2 编写七项要求 ↔ spec 章节对照表，附录在架构文档中
- [x] 18.3 全量测试通过 → commit: `feat(agents): agent-driven architecture complete`
