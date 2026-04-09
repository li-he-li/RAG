## Why

当前后端是单体服务架构，所有 LLM 交互（类案搜索、合同审查、观点预测）直接在 service 函数中硬编码 prompt 并串行调用 DeepSeek。这导致：
1. 无法隔离不同角色的职责（规划/执行/验证混在一个函数里）
2. Prompt 变更需要改代码重新部署
3. 没有 token 预算控制和缓存机制
4. 没有结构化轨迹记录，无法形成改进闭环
5. 零散的 `logger.info` 替代不了集中式遥测

需要将后端从单体服务重构为 **Agent 驱动架构**，前端不动，API 契约不变。

## What Changes

- 引入轻量 Agent 框架（基于 Python asyncio，不依赖外部 agent 运行时），每个业务域由 Planner → Executor → Validator 三个角色组成 pipeline
- 新建 `backend/app/agents/` 目录，包含类案搜索、合同审查、观点预测三个 agent 组
- 新建 `backend/app/prompts/` 目录，所有 prompt 从 Python 源码中提取为 YAML 模板文件，支持版本化和热加载
- 引入 DSPy 框架用于 prompt 自动优化（Signature + Module + Optimizer）
- 新建 `backend/app/services/analytics/` 集中式遥测服务，替代零散 logging
- 新建 `backend/app/services/trajectory/` 轨迹记录服务，结构化记录每次 agent 运行的输入/输出/中间步骤
- 添加 token 预算系统和 prompt 缓存机制
- 添加 LLM 输出治理层（内容安全过滤、prompt 注入防御）
- 添加 checkpoint/resume 能力，支持中断恢复
- **TDD 驱动**：每个 milestone 先写测试再实现，通过后做 commit

## Capabilities

### New Capabilities

- `agent-framework`: Agent 基础框架 — AgentBase、PlannerAgent、ExecutorAgent、ValidatorAgent 抽象，pipeline 编排器，skill 注册表
- `agent-similar-case`: 类案搜索 Agent 组 — 规划（理解查询、选择策略）、执行（检索+重排+相似度计算）、验证（溯源校验）
- `agent-contract-review`: 合同审查 Agent 组 — 规划（条款分割策略）、执行（差异分析+LLM 审查）、验证（结果一致性）
- `agent-opponent-prediction`: 观点预测 Agent 组 — 规划（案情画像）、执行（论点生成+排序）、验证（报告校验）
- `prompt-registry`: Prompt 注册与版本管理 — YAML 模板文件、热加载、版本号、DSPy Signature 集成
- `token-budget`: Token 预算系统 — 请求前 token 估算、预算分配（系统/检索上下文/生成）、缓存感知的 prompt 组装
- `governance-pipeline`: LLM 输出治理 — 内容安全过滤、prompt 注入检测、输出 schema 校验、不可被模型绕过
- `telemetry-service`: 集中式遥测 — 结构化事件、correlation ID、延迟直方图、token 用量计数、成功率统计
- `trajectory-logging`: 轨迹记录 — 结构化记录每次 agent 运行的完整输入/输出/中间步骤/决策点，支持回放和训练反馈
- `checkpoint-resume`: 断点续跑 — pipeline 状态序列化、中断恢复、脏状态清理、进程泄漏管理

### Modified Capabilities

- `legal-similarity-evidence-search`: 后端 API 路由层保持不变，内部实现从直接调用 service 改为通过 agent pipeline 调度

## Impact

- **后端架构**：`backend/app/` 下新增 `agents/`、`prompts/` 目录；`services/` 下新增 `analytics/`、`trajectory/`
- **依赖**：新增 `dspy-ai`、`pyyaml`、`tiktoken`（token 计数）
- **API 契约**：前端完全不动，所有 `/api/v1/*` 和 `/api/*` 端点保持兼容
- **测试**：每个 capability 对应一套 pytest 测试，TDD 流程
- **部署**：无变化，仍支持 Docker 和本地启动
