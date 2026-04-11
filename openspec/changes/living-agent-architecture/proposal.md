## Why

当前系统有三个致命缺陷：

1. **Agent 层是壳架构**——每个 Agent 只是固定调用一个预定义的服务函数，Planner 永远返回写死的单步计划，Validator 做的是 Pydantic 序列化而非真正的语义验证。Agent 没有自主决策能力。

2. **没有记忆**——每次对话只发 `[system, user]` 两条消息给 LLM，用户问完立刻"失忆"。无法做多轮对话、无法理解上下文引用（"上面提到的条款"），闲聊体验极差。

3. **DSPy 是死代码**——`prompts/optimization.py` 有完整的优化管线，但只在测试中被调用，从未接入生产流程。轨迹数据记了但没人喂给训练闭环，Compounding 原则形同虚设。

要让系统"活起来"且满足 7 项企业要求，必须：把决策权下沉到 Agent 层、加入会话记忆、打通 DSPy 训练闭环。

## What Changes

### Agent 层（Effective / Robust）
- **新增 Orchestrator Agent**：替代路由层 if-else 硬编码，根据意图自主调度
- **Planner 真正规划**：根据输入动态生成多步 ExecutionPlan，支持条件分支和迭代
- **Agent-to-Agent 调用**：Agent 可主动调用其他 Agent（如合同审查调用类案检索佐证）
- **自纠正循环**：验证失败 → Planner 修改策略 → 重新执行 → 重新验证
- **语义验证**：ValidatorAgent 增加可配置的 ValidationRule 链（schema + 业务规则 + 质量评估）

### 记忆系统（Robust / Efficient）
- **新增 ConversationMemory**：同一 session 内保持多轮对话历史
- **Token 预算感知的上下文组装**：在 context_window 限制内优先保留最近 N 轮对话，超出时自动压缩旧消息为摘要
- **闲聊路由**：普通闲聊直接用记忆上下文回复，无需走检索管线

### DSPy 训练闭环（Compounding / Updatable）
- **接入生产流程**：TrajectoryStore 数据定期导出为 DSPy Example 集
- **Bootstrap 优化管线**：定时或手动触发 `optimize_prompt_module()`，产出优化后的 prompt 变体
- **A/B 变体发布**：通过 PromptRegistry 的版本化能力切换 baseline vs optimized prompt

### 保持兼容
- 路由层 API 签名不变，Orchestrator 在路由层之下透明接管
- 现有测试全部通过后再增加新行为

## Capabilities

### New Capabilities
- `agent-orchestrator`: 中央编排器，接收用户意图后自主决定调用哪些 Agent 和工具，替代路由层硬编码调度
- `agent-self-correction`: 验证失败后的自纠正循环机制，Planner 修改策略并重试执行
- `agent-to-agent-calls`: Agent 间互相调用能力，通过 ToolRegistry 注册其他 Agent 为工具，实现跨域协作
- `conversation-memory`: 同一 session 内的多轮对话记忆，支持 token 预算感知的上下文组装和自动压缩
- `dspy-production-pipeline`: DSPy 优化管线接入生产流程，轨迹数据导出 → Bootstrap 优化 → 变体发布

### Modified Capabilities
- `agent-framework`: AgentBase 增加 `can_handle()` 能力声明方法；ExecutionPlan 支持多步、条件分支和迭代；PlannerAgent 从空壳改为真正基于输入动态规划
- `governance-pipeline`: 治理管线扩展覆盖 Agent-to-Agent 调用场景，防止无限递归和权限越级
- `tool-governance`: ToolRegistry 增加 Agent-as-Tool 注册，工具权限分级适配跨 Agent 调用

## Impact

- **backend/app/agents/**: 所有 Agent 文件需重构（base.py, pipeline.py, 各业务 Agent）
- **backend/app/services/memory/**: 新增记忆服务目录
- **backend/app/services/chat.py**: 重构为使用 ConversationMemory 组装 messages
- **backend/app/prompts/optimization.py**: 接入定时/手动触发管线
- **backend/app/routers/**: 路由层简化，增加 memory 和 dspy 相关端点
- **backend/tests/**: 全部测试需要适配新行为
- **数据库新增**: `conversation_messages` 表存储对话历史
- **无前端变更**: API 签名保持不变
