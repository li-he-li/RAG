## Context

当前 `fl app` 后端是标准 FastAPI 单体架构，三个核心业务（类案搜索、合同审查、观点预测）各由一个 ~1000 行的 service 文件实现，直接在 Python 函数中硬编码 prompt 字符串并调用 DeepSeek API。前端为原生 JS 单页应用，通过 `/api/*` 端点交互。

已有基础设施：Pydantic BaseSettings 配置验证、HTTP 中间件栈（API Key、Rate Limit、Security Headers）、PostgreSQL + Qdrant 向量存储、Pydantic schema 模型。

参考实现：Claude Code（`E:\claude-code补全版本`）的 agent 架构模式 — registry pattern、memoization、event-driven、skill 系统、结构化遥测。

## Goals / Non-Goals

**Goals:**
- 将三个业务域从单体 service 重构为 Agent pipeline（Planner → Executor → Validator）
- 所有 prompt 从 Python 源码提取到 YAML 模板，支持热加载和版本化
- 引入 DSPy 进行 prompt 自动优化
- 实现 token 预算系统和缓存感知的 prompt 组装
- 建立集中式遥测服务（结构化事件、correlation ID、指标收集）
- 建立轨迹记录系统（结构化记录运行轨迹供训练反馈）
- 实现 LLM 输出治理（不可被模型绕过的内容安全过滤）
- 实现 checkpoint/resume（断点续跑）
- 前端零改动，API 契约完全兼容
- 严格 TDD 流程，每个 milestone 有测试 + commit

**Non-Goals:**
- 不引入外部 agent 运行时（不用 LangGraph、CrewAI 等）
- 不重构前端代码
- 不改变数据库 schema
- 不改变 Docker 部署方式
- 不做多租户或用户权限系统

## Decisions

### D1: 自建轻量 Agent 框架，不依赖外部 agent 运行时

**选择**: 自建基于 Python asyncio 的 Agent pipeline

**替代方案**: LangGraph（过重，引入太多抽象）、CrewAI（不支持 streaming）、AutoGen（与 FastAPI 集成差）

**理由**: 三个业务域的模式高度一致（规划→执行→验证），需要一个极简的 pipeline 编排器。自建框架只需 ~200 行核心代码，完全掌控，与 FastAPI async 原生集成，支持 streaming 响应。

### D2: Prompt 模板使用 YAML 文件 + DSPy Signature

**选择**: `backend/app/prompts/` 目录下 YAML 文件存储 prompt，运行时通过 DSPy Signature 加载和优化

**替代方案**: Jinja2 模板（太通用，没有优化闭环）、纯 Python 字符串（当前状态，不可维护）

**理由**: YAML 人类可读、支持多段 prompt（system/user/assistant）、版本化方便。DSPy 的 Signature 和 Module 机制可以直接在 YAML prompt 上叠加自动优化（BootstrapFewShot、MIPRO），不需要改代码。

### D3: 遥测使用 OpenTelemetry 协议但不引入完整 OTel 栈

**选择**: 自建 `TelemetryService` 类，输出结构化 JSON 事件，接口对齐 OpenTelemetry 的 Span/Event/Metric 概念

**替代方案**: 完整 OpenTelemetry SDK（太重，需要 Collector、Exporter）、Datadog（商业依赖）

**理由**: 项目是单实例部署，不需要分布式追踪的完整栈。但对齐 OTel 语义可以在未来无缝迁移。

### D4: 轨迹记录存储在 PostgreSQL 新表

**选择**: 新建 `agent_trajectory` 表，存储每次 agent 运行的 JSON 轨迹

**替代方案**: 文件系统（查询困难）、Qdrant（不适合结构化日志）

**理由**: 已有 PostgreSQL 实例，SQLAlchemy 模型定义简单，支持按 session_id / agent_name / 时间范围查询。

### D5: Token 预算使用 tiktoken 估算 + LRU 缓存

**选择**: `tiktoken` 对 prompt 段落做 token 计数，系统 prompt 段使用 LRU 缓存

**理由**: DeepSeek 使用 BPE 分词器，tiktoken 的 `cl100k_base` 足够近似估算。系统 prompt 不变时缓存其 token count 避免重复计算。

### D6: 治理层作为中间件插入在 Agent 输出和 HTTP 响应之间

**选择**: `GovernancePipeline` 类在 agent pipeline 的 Validator 角色之后、HTTP 响应之前执行

**理由**: 确保所有 LLM 输出都经过治理检查，模型无法绕过（因为它不参与治理流程的执行）。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| DSPy 优化可能不适用于中文法律领域 | 先用 DSPy Signature 做结构化 I/O，优化器仅在评估集验证有效后才启用 |
| 重构期间可能破坏现有功能 | 严格 TDD，先写测试验证现有行为，再重构 |
| Token 估算不精确 | tiktoken 是近似值，设置 10% 安全裕度 |
| 轨迹记录增加 DB 负载 | 异步写入 + 批量插入，不阻塞主流程 |
| 自建框架缺乏生态支持 | 框架极简（~200行核心），必要时可迁移到标准框架 |
