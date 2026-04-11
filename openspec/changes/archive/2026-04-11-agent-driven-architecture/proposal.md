## Why

当前后端是单体服务架构，所有 LLM 交互（类案搜索、合同审查、观点预测）直接在 service 函数中硬编码 prompt 并串行调用 DeepSeek。这导致：
1. 无法隔离不同角色的职责（规划/执行/验证混在一个函数里）
2. Prompt 变更需要改代码重新部署
3. 没有 token 预算控制和缓存机制
4. 没有结构化轨迹记录，无法形成改进闭环
5. 零散的 `logger.info` 替代不了集中式遥测

需要将后端从单体服务重构为 **Agent 驱动架构**，前端不动，API 契约不变。

## What Changes

采用**四阶段交付**（详见 design.md → Phased Delivery），核心变更包括：

**Phase 1 — 基础设施（不改路由）：**
- 新建 `backend/app/services/analytics/` 集中式遥测服务，替代零散 logging
- 新建 `backend/app/prompts/` 目录，所有 prompt 从 Python 源码中提取为 YAML 模板文件，支持版本化、热加载和请求级 version pinning
- 添加 token 预算系统和 prompt 缓存机制（安全裕度 25%，自适应校准）

**Phase 2 — Agent 框架 + 治理（框架就绪）：**
- 引入轻量 Agent 框架（基于 Python asyncio，不依赖外部 agent 运行时），支持 Planner → Executor → Validator 全链路和简化 pipeline 拓扑
- 新建 `backend/app/agents/` 目录
- 添加输出治理层（内容安全过滤、prompt 注入防御，流式两层策略）
- 添加工具执行治理层（allowlist、参数校验、side-effect 审批策略）
- 新建 API 兼容适配层，将 agent 内部事件与结果映射回现有 API 响应契约
- 添加健壮性保障：幂等重试、优雅取消（AbortSignal 传播）、async task 泄漏管理
- 录制 golden snapshot contract test 用于后续业务域迁移验证

**Phase 3 — 业务域迁移：**
- 四个业务域（类案搜索、合同审查、观点预测、Chat）逐个走通 Agent pipeline
- 新建 `backend/app/services/trajectory/` 轨迹记录服务，含脱敏与保留策略
- 每迁移一个域即可上线验证，单域级别可回滚

**Phase 4 — 优化闭环（延后，需数据积累）：**
- 引入 DSPy 框架用于 prompt 自动优化（Signature + Module + Optimizer）
- 从 trajectory 表导出评估集，基于 golden set 验证优化效果

**贯穿所有 Phase：** TDD 驱动，每个 milestone 先写测试再实现，通过后做 commit

## Capabilities

### New Capabilities

- `agent-framework`: Agent 基础框架 — AgentBase、PlannerAgent、ExecutorAgent、ValidatorAgent 抽象，pipeline 编排器（支持简化拓扑），skill 注册表 *[Phase 2]*
- `agent-similar-case`: 类案搜索 Agent 组 — 策略选择、检索+重排+相似度计算、溯源校验 *[Phase 3]*
- `agent-contract-review`: 合同审查 Agent 组 — 条款分割策略、差异分析+LLM 审查、结果一致性校验 *[Phase 3]*
- `agent-opponent-prediction`: 观点预测 Agent 组 — 案情画像、论点生成+排序、报告校验 *[Phase 3]*
- `prompt-registry`: Prompt 注册与版本管理 — YAML 模板文件、热加载、版本号、请求级 version pinning *[Phase 1]*
- `compatibility-adapter`: API 兼容适配层 — agent 内部 NDJSON / typed result 映射回现有前端可消费的响应与流格式 *[Phase 2]*
- `token-budget`: Token 预算系统 — 请求前 token 估算（25% 安全裕度 + 自适应校准）、预算分配、缓存感知 prompt 组装 *[Phase 1]*
- `output-governance`: LLM 输出治理 — 内容安全过滤、prompt 注入检测、输出 schema 校验、流式两层策略、不可被模型绕过 *[Phase 2]*
- `tool-governance`: 工具执行治理 — allowlist、参数 schema 校验、side-effect tool 审批、不可被模型绕过 *[Phase 2]*
- `telemetry-service`: 集中式遥测 — 结构化事件、correlation ID、延迟直方图、token 用量计数、成功率统计 *[Phase 1]*
- `trajectory-logging`: 轨迹记录 — 结构化记录 agent 运行轨迹、prompt 版本快照、脱敏与保留策略，支持回放和训练反馈 *[Phase 3]*
- `robustness`: 健壮性保障 — 幂等重试、优雅取消、async task 泄漏管理、脏状态清理 *[Phase 2]*
- `dspy-optimization`: DSPy prompt 自动优化 — Signature + Module + Optimizer，基于轨迹评估集 *[Phase 4, 延后]*

### Modified Capabilities

- `legal-similarity-evidence-search`: 后端 API 路由层保持不变，内部实现从直接调用 service 改为通过 agent pipeline 调度

## Impact

- **后端架构**：`backend/app/` 下新增 `agents/`、`prompts/` 目录；`services/` 下新增 `analytics/`、`trajectory/`
- **依赖**：Phase 1–3 新增 `pyyaml`、`tiktoken`、`watchfiles`（热加载）；Phase 4 新增 `dspy-ai`
- **API 契约**：前端完全不动，所有 `/api/v1/*` 和 `/api/*` 端点通过 compatibility adapter 保持兼容
- **测试**：每个 capability 对应一套 pytest 测试，TDD 流程；Phase 2 起增加 golden snapshot contract test
- **部署**：无变化，仍支持 Docker 和本地启动
