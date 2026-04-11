## Context

当前系统有三大缺陷需要同时解决：

1. Agent 层是壳架构（Planner 写死计划、Validator 做 pass）
2. 没有记忆（每次对话只发 system+user 两条消息）
3. DSPy 是死代码（有优化管线但从未接入生产）

参考实现 `E:\claude-code补全版本` 的记忆系统：基于 session 的 JSONL 存储 + auto-compact（token 预算耗尽前自动压缩旧消息为摘要）+ 上下文窗口管理。

## Goals / Non-Goals

**Goals:**
- 同一 session 内多轮对话有完整记忆，能理解上下文引用
- 闲聊不走检索管线，直接基于记忆上下文回复（不死板）
- Orchestrator 替代路由层 if-else
- Planner 动态生成多步计划
- Agent 可调用其他 Agent（通过 ToolRegistry）
- 自纠正循环（验证失败 → 重试）
- DSPy 优化管线真正跑起来（轨迹 → 训练集 → 优化 → 变体发布）
- 所有行为受治理管线约束
- 严格 TDD，每 milestone 一个 commit

**Non-Goals:**
- 不引入外部 Agent 框架（LangChain/CrewAI）
- 不做跨 session 记忆（Phase 1 只做 session 内记忆）
- 不做分布式 Agent
- 不做 LLM-as-Planner（Planner 用规则 + 语义匹配）
- 不做自动 prompt 优化触发（Phase 1 手动/API 触发，Phase 2 再做定时）
- 不改前端

## Decisions

### D1: 记忆存储用 PostgreSQL，不用文件

**选择**: 新增 `conversation_messages` 表，存储在 PostgreSQL。

**而非**: 像 Claude Code 参考实现那样用 JSONL 文件。

**理由**: 项目已有 PostgreSQL 且用于所有持久化数据。用文件存储会引入两套存储系统、数据一致性问题、备份复杂度。PostgreSQL 提供查询、索引、事务。

**Schema**:
```sql
conversation_messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,        -- system/user/assistant/tool
    content TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
)
CREATE INDEX idx_conv_msg_session_created ON conversation_messages(session_id, created_at);
```

### D2: 上下文组装策略 — 滑动窗口 + 自动压缩

**选择**: 从 conversation_messages 按 session_id 加载最近消息，受 TokenBudget 约束。超出预算时压缩旧消息为摘要。

**参考**: Claude Code 的 auto-compact 机制。

**实现**:
1. 加载最近 N 条消息（按 token_count 总和 <= budget）
2. 如果最旧的消息被截断，调用 LLM 生成摘要替代
3. 组装顺序: `[system_prompt, summary(如有), 保留的历史消息, 当前用户消息]`
4. 摘要存储为 role=`system`, metadata=`{"type": "compact_summary"}` 的特殊消息

### D3: 闲聊直接用记忆回复，不走检索

**选择**: ChatAgent 的 `_should_skip_retrieval()` 命中时，直接用记忆上下文（历史对话）回复，不调用检索管线。

**而非**: 走完整的检索 → 构建上下文 → 回复流程。

**理由**: "你好"、"谢谢"、"帮我总结一下刚才说的"这类消息不需要检索法律文书。强制走检索浪费 token 和时间，体验也差。

**实现**: `_should_skip_retrieval()` 返回 True 时，组装 `[system闲聊prompt, 历史消息, 当前消息]` 直接调 DeepSeek。

### D4: Orchestrator 用规则路由

**选择**: Orchestrator 用 IntentRouter（endpoint path + payload 字段）做确定性路由。

**而非**: 用 LLM 做路由。

**理由**: 路由决策频率极高，LLM 路由增加 ~500ms 延迟 + token 成本 + 不确定性。违背 Efficient 原则。

### D5: Agent-as-Tool 通过 ToolRegistry 注册

**选择**: 将 Agent 包装为 GovernedTool 注册到 ToolRegistry，其他 Agent 通过 `invoke_tool()` 调用。

**而非**: Agent 直接 import 其他 Agent。

**理由**: 统一治理入口（权限、审计、递归防护），解耦 Agent 间依赖。

### D6: 自纠正循环在 Pipeline 层

**选择**: `AgentPipeline` 增加 `max_retries`，验证失败时回到 Planner 重新规划。

**而非**: 每个 Agent 自己实现重试。

**理由**: 重试是流程级关注点；Planner 可以根据失败原因修改整体策略。

### D7: DSPy 优化管线接入

**选择**:
1. TrajectoryStore 记录的轨迹数据通过 `export_trajectory_evalset()` 导出为 DSPy Example
2. 通过 API 端点 `POST /api/admin/optimize-prompt` 手动触发 `optimize_prompt_module()`
3. 优化后的 prompt 变体通过 `build_ab_test_variants()` 注册到 PromptRegistry
4. PromptRegistry 的版本化能力切换 baseline vs optimized

**而非**: 自动定时优化。

**理由**: Phase 1 先手动触发确保可控，验证效果后再做自动化。定时任务需要 scheduler（celery/APScheduler），增加部署复杂度。

### D8: Planner 用策略模式

**选择**: 每个 PlannerAgent 实现多个 `PlanningStrategy`，根据输入特征选择策略。

**实现**: 简单请求 → 单步计划；复杂请求 → 多步 + 跨 Agent 调用。

## Risks / Trade-offs

**[记忆膨胀]** 长对话 session 可能积累大量消息
→ auto-compact 在 token 预算 80% 时触发摘要压缩

**[递归调用]** Agent A → Agent B → Agent A 无限循环
→ ToolGovernancePolicy 强制 max_depth=3

**[DSPy 优化质量]** BootstrapFewShot 依赖标注数据质量
→ Phase 1 先用 exact_match metric，后续引入人工标注

**[向后兼容]** 路由层重构可能影响现有行为
→ Orchestrator 初始行为与现有路由 if-else 完全一致

**[闲聊边界]** 判断"闲聊"vs"法律咨询"的边界模糊
→ Phase 1 用关键词列表 + 短文本判断，Phase 2 用分类模型

**[数据库迁移]** 新增 conversation_messages 表
→ 单独 migration 文件，不影响现有表
