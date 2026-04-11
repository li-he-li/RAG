# Phase 3 Agent Migration

更新日期：2026-04-11

## 范围

phase 3 负责把四条核心业务链路迁移到 agent pipeline，并保持 HTTP 契约兼容。

## 已完成内容

### 1. 四个业务域全部迁移

- `similar-case`
- `contract-review`
- `opponent-prediction`
- `chat`

### 2. 兼容层接管旧 API 输出

- 非流式接口通过 `adapt_response()` 返回旧 JSON 结构
- 流式接口通过 `adapt_stream()` 过滤内部事件，只保留公开事件类型

### 3. phase 3 集成测试覆盖四条链路

- similar-case JSON contract
- contract-review NDJSON event contract
- chat NDJSON event contract
- opponent-prediction JSON contract

## 当前达成的架构性质

### Effective

四个业务域都不再直接从 router 调用单个服务函数返回结果，而是通过 agent pipeline 运行。

### Safe

所有 pipeline 输出都会进入治理层；流式接口额外包含 per-chunk 与 post-stream 两层治理。

### Monitorable

每个 agent step 都可以产生统一的 telemetry 和 trajectory 证据。

### Compounding

phase 3 后，系统已经具备从真实业务流量中采集结构化轨迹的能力，为 phase 4 的评估与优化准备了底座。

## 迁移原则

- 不破坏旧前端契约
- 不为了迁移而重写成熟领域服务
- 先建立系统级骨架，再迭代优化 agent 能力
- 每个 milestone 都以测试和提交作为完成标准
