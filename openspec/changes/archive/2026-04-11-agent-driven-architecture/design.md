## Context

当前 `fl app` 后端是标准 FastAPI 单体架构，三个核心业务（类案搜索、合同审查、观点预测）各由一个 ~600–1100 行的 service 文件实现，直接在 Python 函数中硬编码 prompt 字符串并调用 DeepSeek API。前端为原生 JS 单页应用，通过 `/api/*` 端点交互。

已有基础设施：Pydantic BaseSettings 配置验证、HTTP 中间件栈（API Key、Rate Limit、Security Headers）、PostgreSQL + Qdrant 向量存储、Pydantic schema 模型。

参考实现：Claude Code（`E:\claude-code补全版本`）的 agent 架构模式 — registry pattern、memoization、event-driven、skill 系统、结构化遥测。

## Phased Delivery

本次变更规模较大（新增 ~10 个模块，涉及 80+ 任务项），采用 **四阶段交付** 以降低风险。每个 Phase 独立可回滚、可验证、可 commit。

| Phase | 范围 | 交付物 | 可独立回滚 |
|-------|------|--------|-----------|
| **Phase 1: 基础设施** | 遥测服务 + Prompt 注册表 + Token 预算 | 不改路由，纯后端横切能力 | 是 |
| **Phase 2: Agent 框架 + 治理** | Agent 框架核心 + 输出治理 + 工具治理 + Compatibility Adapter + 健壮性（幂等重试/优雅取消） | 框架就绪但未接业务域 | 是 |
| **Phase 3: 业务域迁移** | 四个业务域逐个走通 Agent pipeline + 轨迹记录 + golden snapshot contract test | 每迁移一个域即可上线验证 | 单域级别可回滚 |
| **Phase 4: 优化闭环** | DSPy 集成 + 基于轨迹的 prompt 自动优化 | 需轨迹数据积累 ≥200 条 + 人工 golden set | 是 |

## Goals / Non-Goals

**Goals:**
- 将三个业务域从单体 service 重构为 Agent pipeline（支持 Planner → Executor → Validator 全链路，也允许业务域按需省略 Planner 或 Validator 的简化 pipeline）
- 所有 prompt 从 Python 源码提取到 YAML 模板，支持热加载和版本化
- 保持现有 HTTP/streaming 响应契约不变，agent 内部事件通过 compatibility adapter 映射到既有 API 格式
- 实现 token 预算系统和缓存感知的 prompt 组装
- 建立集中式遥测服务（结构化事件、correlation ID、指标收集）
- 建立轨迹记录系统（结构化记录运行轨迹供训练反馈）
- 实现工具执行治理与输出治理（不可被模型绕过的 allowlist、参数校验、审批策略、内容安全过滤）
- 实现请求级 prompt version pinning，并把 prompt 快照、脱敏与保留策略纳入轨迹治理
- 实现健壮性保障：幂等重试、优雅取消（AbortSignal 传播）、async task 泄漏管理、脏状态清理
- 前端零改动，API 契约完全兼容
- 严格 TDD 流程，每个 milestone 有测试 + commit
- （Phase 4，延后）引入 DSPy 进行 prompt 自动优化，前提是轨迹数据积累充足

**Non-Goals:**
- 不引入外部 agent 编排运行时（不用 LangGraph、CrewAI、AutoGen 等）
- 不重构前端代码
- 不改变现有数据库表结构（但允许新增表，如 `agent_trajectory`）
- 不改变 Docker 部署方式
- 不做多租户或用户权限系统
- 不做完整 checkpoint/resume 状态序列化（当前请求延迟 5–40 秒，用户重试比恢复陈旧 checkpoint 更自然）

## Decisions

### D1: 自建轻量 Agent 框架，不依赖外部 agent 运行时

**选择**: 自建基于 Python asyncio 的 Agent pipeline

**替代方案**: LangGraph（过重，引入太多抽象）、CrewAI（不支持 streaming）、AutoGen（与 FastAPI 集成差）

**理由**: 三个业务域的模式高度一致（规划→执行→验证），需要一个轻量的 pipeline 编排器。自建框架预计 ~1500 行核心代码（含 Governance、Telemetry 集成），完全掌控，与 FastAPI async 原生集成，支持 streaming 响应。

**隔离级别说明**: 当前采用**单进程多协程 + 角色类分离**（Planner / Executor / Validator 为独立类，互不共享可变状态，通过方法参数传递 pipeline 上下文），不引入子进程或消息队列。如果未来需要更强隔离（如 Validator 运行在独立沙箱中），框架的 AgentBase 接口不变，只需将 `run()` 实现替换为 RPC 调用。

**简化 pipeline**: 框架允许业务域按需省略 Planner 或 Validator。例如类案搜索的策略选择可退化为一个同步函数而非完整 PlannerAgent，pipeline 支持 `[Executor]`、`[Executor → Validator]`、`[Planner → Executor → Validator]` 三种拓扑。

### D2: Prompt 模板使用 YAML 文件，DSPy 延后到 Phase 4

**选择**: `backend/app/prompts/` 目录下 YAML 文件存储 prompt，Phase 1–3 使用纯 YAML + `{{var}}` 替换；Phase 4 在轨迹数据积累充足后引入 DSPy Signature 叠加自动优化

**替代方案**: Jinja2 模板（太通用，没有优化闭环）、纯 Python 字符串（当前状态，不可维护）

**理由**: YAML 人类可读、支持多段 prompt（system/user/assistant）、版本化方便。DSPy 延后的原因：(1) DSPy Optimizer 核心依赖 GPT-4/Claude 做 meta-prompt 生成，对 DeepSeek 非一等公民支持；(2) 中文法律领域 prompt 优化需要标注评估集，轨迹数据刚开始积累时不够用；(3) 纯 YAML 已能满足 Phase 1–3 的 Updatable 要求。

### D3: 遥测使用 OpenTelemetry 协议但不引入完整 OTel 栈

**选择**: 自建 `TelemetryService` 类，输出结构化 JSON 事件，接口对齐 OpenTelemetry 的 Span/Event/Metric 概念

**替代方案**: 完整 OpenTelemetry SDK（太重，需要 Collector、Exporter）、Datadog（商业依赖）

**理由**: 项目是单实例部署，不需要分布式追踪的完整栈。但对齐 OTel 语义可以在未来无缝迁移。

### D4: 轨迹记录存储在 PostgreSQL 新表

**选择**: 新建 `agent_trajectory` 表，存储每次 agent 运行的 JSON 轨迹

**替代方案**: 文件系统（查询困难）、Qdrant（不适合结构化日志）

**理由**: 已有 PostgreSQL 实例，SQLAlchemy 模型定义简单，支持按 session_id / agent_name / 时间范围查询。

### D5: Token 预算使用 tiktoken 估算 + LRU 缓存 + 自适应校准

**选择**: `tiktoken` 对 prompt 段落做 token 计数，系统 prompt 段使用 LRU 缓存

**理由**: DeepSeek-V2/V3 使用自有 BPE 分词器，与 tiktoken 的 `cl100k_base` 在中文字符上存在显著差异（实测中文长文本误差可达 20–30%）。因此：
1. **安全裕度设为 25%**（而非 10%），确保不会因低估而超出上下文窗口
2. 引入**自适应校准机制**：记录每次 API 调用的 actual token usage，当 actual 与 estimated 的比值偏差超过 15% 时，自动调整后续请求的校准系数
3. 若未来需要精确计算，可替换为 DeepSeek 官方 tokenizer（`transformers.AutoTokenizer`），接口不变

### D6: 治理层作为中间件插入在 Agent 输出和 HTTP 响应之间，流式采用两层策略

**选择**: `GovernancePipeline` 类在 agent pipeline 的 Validator 角色之后、HTTP 响应之前执行

**理由**: 确保所有 LLM 输出都经过治理检查，模型无法绕过（因为它不参与治理流程的执行）。

**流式治理两层策略**（写死，实现时不可自行变更）：
1. **流式层（per-chunk）**: 仅做轻量 pattern scan — 注入关键词黑名单 + 已知高危正则。遇到可疑 chunk 时中断流并发送 `governance_blocked` 终止事件。不做 schema 校验（部分 JSON 无意义）、不做完整 PII 检测（可能跨 chunk 边界）。
2. **聚合层（post-stream）**: 流结束后对完整拼接输出做全量治理 — PII 检测、schema 校验、深度注入检测。若不通过，追加一个 `governance_retracted` 事件通知客户端撤回先前内容。
3. 非流式端点只走聚合层治理（Validator 之后、JSON 响应之前）。

### D7: 增加 compatibility adapter，而不是让前端直接消费 agent 内部事件

**选择**: agent pipeline 内部允许使用 typed result 和内部 NDJSON 事件；所有对外接口通过 `CompatibilityAdapter` 转换为当前前端已消费的 JSON / streaming 契约

**替代方案**: 直接把 `plan_created`、`step_started` 等内部事件暴露给前端（会破坏现有 API 契约）

**理由**: proposal 已承诺前端零改动与 API 完全兼容。兼容适配层把“内部演进”与“外部契约”解耦，允许逐步替换 router 内部实现而不影响线上客户端。

### D8: Safe 采用“两段式治理”，工具执行前治理 + 输出返回前治理

**选择**: 在 Planner / Executor 使用 tool 前执行 `ToolGovernancePolicy`；在 Validator 之后、HTTP 返回之前执行 `OutputGovernancePipeline`

**替代方案**: 仅做输出过滤（不能满足工具执行治理要求）

**理由**: 企业级 Safe 要求是“工具执行治理且不可绕过”，而不仅是文本输出审查。工具调用必须经过 allowlist、参数 schema 校验、side-effect 分级和审批策略，模型本身不能跳过这些检查。

### D9: Prompt 版本按请求锁定，轨迹默认脱敏并带保留策略

**选择**: 请求开始时解析并锁定所用 prompt 版本；同一请求生命周期内 Planner / Executor / Validator 使用固定版本。Trajectory 默认存脱敏摘要和必要快照，原文保留由配置显式开启并受 TTL 控制。

**替代方案**: 热加载后立即影响所有在途请求，或在轨迹中无约束保存全文

**理由**: request-scoped pinning 保证回放、审计和故障定位可重复；默认脱敏和 TTL 可降低法律文本、PII 和敏感材料进入长期存储的风险。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| DSPy 优化可能不适用于中文法律领域 | Phase 4 延后引入，前提是轨迹 ≥200 条 + 人工 golden set 验证有效 |
| 重构期间可能破坏现有功能 | 严格 TDD + Phase 3 开始前录制 golden snapshot contract test |
| Token 估算不精确（DeepSeek 中文 vs tiktoken 差异 20–30%） | 安全裕度 25% + 自适应校准机制，持续比对 estimated vs actual |
| 轨迹记录增加 DB 负载 | 异步写入 + 批量插入，不阻塞主流程 |
| 自建框架缺乏生态支持 | 框架 ~1500 行核心代码，接口对齐业界模式，必要时可迁移到标准框架 |
| compatibility adapter 漏掉边缘响应格式 | 为每个既有端点增加 golden response / golden stream 兼容测试 |
| 轨迹保存敏感文本带来合规风险 | 默认脱敏、字段级白名单、TTL 与审计查询 |
| 全量变更一次交付风险过高 | 四阶段交付，每个 Phase 独立可回滚可验证 |
| 流式治理对 chunk 做完整校验不可行 | 两层策略写死：per-chunk 轻量 scan + post-stream 全量治理 |
