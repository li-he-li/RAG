# Agent-Driven Architecture Overview

更新日期：2026-04-11

## 目标

本系统采用渐进式 agent-driven architecture。目标不是为了引入复杂概念，而是在不破坏既有 API 契约的前提下，把关键业务路径迁移到可治理、可观测、可追踪、可升级的执行框架上。

## 分层

### HTTP / Router Layer

- FastAPI router 继续对外暴露既有端点
- router 只负责参数校验、依赖注入和 compatibility adapter 装配

### Compatibility Layer

- `app.agents.compatibility.CompatibilityAdapter`
- 作用：把内部 typed result 和内部流式事件映射为旧前端已经依赖的 JSON/NDJSON contract
- 结果：迁移内部架构时，外部接口保持稳定

### Agent Pipeline Layer

- `AgentPipeline` 支持三种拓扑：
  - `[Executor]`
  - `[Executor -> Validator]`
  - `[Planner -> Executor -> Validator]`
- pipeline 统一承载：
  - 角色隔离
  - 轨迹记录
  - 输出治理
  - streaming 处理

### Governance Layer

- `ToolGovernancePolicy`: 工具调用前治理
- `OutputGovernancePipeline`: 输出前、流中、流后治理
- 治理不由模型自行决定，执行入口在系统代码中固定

### Services Layer

原有检索、聊天、合同审查、预测等服务继续承担领域逻辑。agent 层主要负责编排和治理，而不是重写已有成熟业务逻辑。

### OS-level Support Services

- `services/analytics/`: 遥测、correlation id、token 计量
- `services/trajectory/`: 结构化轨迹记录、脱敏、保留策略、查询
- `prompts/registry.py`: 模块化 prompt 注册、版本化和热加载

## 业务域拓扑

### Similar Case

- 路由：`/api/v1/similar-cases/compare`
- 拓扑：`[Executor -> Validator]`
- 原因：策略选择较轻，不需要单独 planner

### Contract Review

- 路由：`/api/v1/contract-review/stream`
- 拓扑：`[Planner -> Executor -> Validator]`
- 原因：合同审查需要先做条款和模板规划，再执行流式审查，最后统一校验结果

### Opponent Prediction

- 路由：`/api/v1/opponent-prediction/start`
- 拓扑：`[Planner -> Executor -> Validator]`
- 原因：需要先构建案情画像和争议焦点，再生成预测结果并校验完整性

### Chat

- 路由：`/api/v1/chat/stream`
- 拓扑：`[Executor -> Validator]`
- 原因：主要成本在检索与流式生成，但仍需要引用一致性校验

## 为什么不是“全都改成多进程智能体”

当前实现采用的是职责隔离，而不是引入不必要的运行时复杂度：

- 规划、执行、验证在系统模块和类边界上清晰隔离
- 治理、遥测、轨迹以系统层服务统一承载
- 原有业务服务被保留，避免为“看起来高级”而重写稳定代码

这符合当前交付阶段的最佳实践：先建立可治理的架构骨架，再逐步把优化和自动调参能力叠加进去。
