## 1. 基础设施与依赖

- [ ] 1.1 添加新依赖到 requirements.txt：`dspy-ai>=2.5`、`pyyaml>=6.0`、`tiktoken>=0.7`、`opentelemetry-api>=1.20`
- [ ] 1.2 创建目录结构：`backend/app/agents/`、`backend/app/prompts/`、`backend/app/services/analytics/`、`backend/app/services/trajectory/`
- [ ] 1.3 创建 `backend/app/agents/__init__.py`、`backend/app/prompts/__init__.py`、`backend/app/services/analytics/__init__.py`、`backend/app/services/trajectory/__init__.py`

## 2. 遥测服务 (Monitorable)

- [ ] 2.1 TDD: 编写 `tests/test_telemetry.py` — 测试事件记录、correlation ID 传播、指标收集
- [ ] 2.2 实现 `backend/app/services/analytics/telemetry.py` — TelemetryService 单例（结构化 JSON 事件、correlation_id、延迟直方图、token 计数）
- [ ] 2.3 实现 `backend/app/services/analytics/middleware.py` — FastAPI 中间件自动注入 correlation ID
- [ ] 2.4 运行测试确认通过 → commit: `feat(telemetry): add centralized telemetry service`

## 3. Prompt 注册表 (Updatable)

- [ ] 3.1 TDD: 编写 `tests/test_prompt_registry.py` — 测试 YAML 加载、变量替换、版本追踪
- [ ] 3.2 实现基础 PromptRegistry：`backend/app/prompts/registry.py` — YAML 加载、`{{var}}` 替换、版本号
- [ ] 3.3 从现有代码中提取所有 prompt 到 YAML 文件：
  - `backend/app/prompts/similar_case_search.yaml`
  - `backend/app/prompts/contract_review.yaml`
  - `backend/app/prompts/opponent_prediction.yaml`
  - `backend/app/prompts/chat.yaml`
  - `backend/app/prompts/retrieval_explanation.yaml`
- [ ] 3.4 实现热加载：文件变更时自动重新加载 prompt 模板
- [ ] 3.5 运行测试确认通过 → commit: `feat(prompts): extract prompts to YAML with hot-reload`

## 4. DSPy 集成 (Updatable + Compounding)

- [ ] 4.1 TDD: 编写 `tests/test_dspy_signatures.py` — 测试 DSPy Signature 加载和输入输出
- [ ] 4.2 为每个业务域创建 DSPy Signature：`backend/app/prompts/signatures.py`
- [ ] 4.3 创建 DSPy Module 包装器，将 YAML prompt 映射到 DSPy Signature
- [ ] 4.4 实现评估集加载和优化器配置（BootstrapFewShot）
- [ ] 4.5 运行测试确认通过 → commit: `feat(dspy): integrate DSPy for prompt optimization`

## 5. Token 预算系统 (Efficient)

- [ ] 5.1 TDD: 编写 `tests/test_token_budget.py` — 测试 token 计数、预算分配、缓存
- [ ] 5.2 实现 TokenBudgetManager：`backend/app/services/analytics/token_budget.py` — tiktoken 计数、预算分配、LRU 缓存
- [ ] 5.3 集成到 prompt 组装流程：发送前自动估算，超限拒绝
- [ ] 5.4 运行测试确认通过 → commit: `feat(token-budget): add token estimation and budget system`

## 6. Agent 框架核心 (Effective)

- [ ] 6.1 TDD: 编写 `tests/test_agent_framework.py` — 测试 AgentBase、Pipeline 编排、streaming
- [ ] 6.2 实现 AgentBase 抽象类：`backend/app/agents/base.py` — run()、validate()、name 属性
- [ ] 6.3 实现 PlannerAgent、ExecutorAgent、ValidatorAgent 抽象
- [ ] 6.4 实现 AgentPipeline 编排器：Planner→Executor→Validator 链式调用，支持 streaming
- [ ] 6.5 实现 SkillRegistry：`backend/app/agents/registry.py` — 按 name 注册和发现 agent
- [ ] 6.6 运行测试确认通过 → commit: `feat(agents): add agent framework with pipeline orchestration`

## 7. 轨迹记录 (Compounding)

- [ ] 7.1 TDD: 编写 `tests/test_trajectory.py` — 测试轨迹记录、查询、回放
- [ ] 7.2 创建数据库表：`agent_trajectory` — session_id, agent_name, step_type, input_hash, output, duration_ms, token_usage
- [ ] 7.3 实现 TrajectoryLogger：`backend/app/services/trajectory/logger.py` — 异步写入、不阻塞主流程
- [ ] 7.4 集成到 AgentPipeline：每个 agent step 自动记录轨迹
- [ ] 7.5 添加查询 API：`GET /api/v1/trajectories/{session_id}`
- [ ] 7.6 运行测试确认通过 → commit: `feat(trajectory): add structured trajectory logging`

## 8. LLM 输出治理 (Safe)

- [ ] 8.1 TDD: 编写 `tests/test_governance.py` — 测试安全过滤、注入检测、schema 校验
- [ ] 8.2 实现 GovernancePipeline：`backend/app/agents/governance.py` — 内容安全、注入检测、schema 校验
- [ ] 8.3 集成到 AgentPipeline：Validator 之后、HTTP 响应之前
- [ ] 8.4 实现审计日志：记录所有治理决策（pass/block/log）
- [ ] 8.5 运行测试确认通过 → commit: `feat(governance): add LLM output governance pipeline`

## 9. 断点续跑 (Robust)

- [ ] 9.1 TDD: 编写 `tests/test_checkpoint.py` — 测试状态序列化、恢复、清理
- [ ] 9.2 实现 CheckpointManager：`backend/app/agents/checkpoint.py` — 序列化 pipeline 状态
- [ ] 9.3 实现 resume：pipeline 启动时检查已有 checkpoint，从上次完成步骤继续
- [ ] 9.4 实现脏状态清理：启动时清理超过 TTL 的孤立 checkpoint
- [ ] 9.5 实现进程泄漏管理：追踪 async task，shutdown 时取消孤儿任务
- [ ] 9.6 实现优雅取消：前端 AbortSignal 传播到后端 async LLM 调用
- [ ] 9.7 运行测试确认通过 → commit: `feat(checkpoint): add pipeline checkpoint and resume`

## 10. 类案搜索 Agent (Effective)

- [ ] 10.1 TDD: 编写 `tests/test_agent_similar_case.py` — 测试规划、执行、验证
- [ ] 10.2 实现 SimilarCasePlanner：查询理解、策略选择（vector/keyword/hybrid）
- [ ] 10.3 实现 SimilarCaseExecutor：调用现有 retrieval + similar_case_search 服务
- [ ] 10.4 实现 SimilarCaseValidator：调用 traceability 验证 + 溯源校验
- [ ] 10.5 修改 search router：`/api/v1/similar-cases/compare` 路由改为通过 agent pipeline 调度
- [ ] 10.6 运行测试确认 API 响应格式兼容 → commit: `feat(agents): similar-case search agent pipeline`

## 11. 合同审查 Agent (Effective)

- [ ] 11.1 TDD: 编写 `tests/test_agent_contract_review.py` — 测试规划、执行、验证、streaming
- [ ] 11.2 实现 ContractReviewPlanner：条款分割策略、模板匹配
- [ ] 11.3 实现 ContractReviewExecutor：差异分析 + LLM 审查
- [ ] 11.4 实现 ContractReviewValidator：findings 一致性校验
- [ ] 11.5 修改 search router：`/api/v1/contract-review/stream` 改为通过 agent pipeline
- [ ] 11.6 运行测试确认 streaming 格式兼容 → commit: `feat(agents): contract review agent pipeline`

## 12. 观点预测 Agent (Effective)

- [ ] 12.1 TDD: 编写 `tests/test_agent_opponent_prediction.py` — 测试规划、执行、验证
- [ ] 12.2 实现 PredictionPlanner：案情画像构建、争议焦点推断
- [ ] 12.3 实现 PredictionExecutor：论点生成、证据检索、论点排序
- [ ] 12.4 实现 PredictionValidator：报告完整性校验
- [ ] 12.5 修改 prediction router：路由改为通过 agent pipeline
- [ ] 12.6 运行测试确认 API 响应格式兼容 → commit: `feat(agents): opponent prediction agent pipeline`

## 13. Chat Agent (Effective)

- [ ] 13.1 TDD: 编写 `tests/test_agent_chat.py` — 测试 chat agent pipeline
- [ ] 13.2 实现 ChatPlanner：查询意图识别、检索决策
- [ ] 13.3 实现 ChatExecutor：检索 + DeepSeek 流式生成
- [ ] 13.4 实现 ChatValidator：citation 一致性校验
- [ ] 13.5 修改 search router：`/api/v1/chat/stream` 改为通过 agent pipeline
- [ ] 13.6 运行测试确认 streaming 格式兼容 → commit: `feat(agents): chat agent pipeline`

## 14. 集成测试与最终验证

- [ ] 14.1 编写端到端集成测试：完整 agent pipeline 从 HTTP 请求到响应
- [ ] 14.2 验证所有 7 项企业要求达标（Effective/Efficient/Safe/Robust/Monitorable/Updatable/Compounding）
- [ ] 14.3 更新审计报告 `docs/代码质量审计报告.md`
- [ ] 14.4 更新 `docs/` 下的架构文档
- [ ] 14.5 全量测试通过 → commit: `feat(agents): agent-driven architecture complete`
