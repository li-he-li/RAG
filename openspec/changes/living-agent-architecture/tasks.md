## 1. 记忆存储层 — ConversationMessage 模型与持久化

- [x] 1.1 创建 SQLAlchemy 模型 `ConversationMessage`（id, session_id, role, content, token_count, created_at, metadata）
- [ ] 1.2 创建 Alembic migration 文件新增 `conversation_messages` 表 + 索引 `idx_conv_msg_session_created`
- [x] 1.3 创建 `app/services/memory/store.py`：`save_message()`, `load_messages(session_id, limit)`, `delete_session(session_id)`, `cleanup_old_sessions(max_age_hours=24)`
- [x] 1.4 编写测试：消息 CRUD、按 session 查询有序、cleanup 只删旧 session
- [x] 1.5 运行全部测试 → committed

## 2. Token 预算感知的上下文组装

- [x] 2.1 创建 `app/services/memory/context_assembler.py`
- [x] 2.2 实现 token 预算计算
- [x] 2.3 实现 auto-compact
- [x] 2.4 组装最终 messages 数组
- [x] 2.5 编写测试
- [x] 2.6 运行全部测试 → committed

## 3. Chat 服务接入记忆 — 多轮对话

- [x] 3.1 重构 `_build_deepseek_payload()`：接收 history_messages 参数
- [x] 3.2 在 `execute_grounded_chat()` 和 `stream_grounded_chat()` 中：保存用户消息 → 组装上下文 → 调用 LLM → 保存助手响应
- [x] 3.3 确保 grounded 模式下 messages 格式正确
- [x] 3.4 确保非 grounded 模式下 messages 格式正确
- [x] 3.5 编写测试
- [x] 3.6 运行全部测试 → committed

## 4. 闲聊记忆路径 — 不死板

- [x] 4.1 扩展 `_should_skip_retrieval()` 添加更多闲聊模式
- [x] 4.2 实现 `handle_casual_chat()`：记忆+友好系统提示
- [x] 4.3 casual_system_prompt 设计
- [x] 4.4 编写测试
- [x] 4.5 运行全部测试 → committed

## 5. AgentBase 扩展 — can_handle + ValidationRule

- [x] 5.1 在 `AgentBase` 中新增 `can_handle(input) -> float`
- [x] 5.2 为 4 个现有 Agent 实现 `can_handle()`
- [x] 5.3 新增 `ValidationRule` 协议类
- [ ] 5.4 为现有 4 个 Validator 各实现至少 2 条 ValidationRule
- [x] 5.5 编写测试
- [x] 5.6 运行全部测试 → committed

## 6. ExecutionPlan 扩展 — 条件分支

- [x] 6.1 在 `PlanStep` 中新增 `condition: str | None` 字段
- [x] 6.2 在 `PlanStep` 中新增 `parallel_group: str | None` 字段
- [x] 6.3 在 `AgentPipeline` 中实现条件评估
- [x] 6.4 编写测试
- [x] 6.5 运行全部测试 → committed

## 7. PlanningStrategy — 动态规划

- [x] 7.1 定义 `PlanningStrategy` 协议
- [x] 7.2 ContractReviewPlanner: classify_complexity → 多步计划
- [x] 7.3 PredictionPlanner: classify_complexity → 多步计划
- [x] 7.4 编写测试
- [x] 7.5 运行全部测试 → committed

## 8. 自纠正循环

- [x] 8.1 `max_retries: int = 2`
- [x] 8.2 Validator 返回 Rejection → 重新规划
- [x] 8.3 将 Rejection 传回 Planner
- [x] 8.4 非 retryable 错误直接返回
- [x] 8.5 编写测试
- [x] 8.6 运行全部测试 → committed

## 9. Agent-as-Tool 注册 + 递归防护

- [x] 9.1 新增 `AgentTool` 包装类
- [x] 9.2 将 4 个 Agent 注册为 Tool（register_agents_as_tools）
- [x] 9.3 ToolGovernancePolicy max_recursion_depth=3
- [x] 9.4 编写测试
- [x] 9.5 运行全部测试 → committed

## 10. Agent 间协作 — 业务层启用

- [x] 10.1 ContractReviewExecutor 复杂策略中增加可选步骤
- [ ] 10.2 PredictionExecutor evidence_backed 策略中调用 retrieval 工具
- [x] 10.3 输出结构扩展包含 cross_references 字段
- [x] 10.4 编写测试
- [x] 10.5 运行全部测试 → committed

## 11. Orchestrator Agent

- [x] 11.1 实现 `IntentRouter`
- [x] 11.2 实现 `OrchestratorAgent`
- [x] 11.3 覆盖全部现有路由的 intent 规则
- [x] 11.4 未知 intent fallback 到 Chat + 遥测
- [x] 11.5 编写测试
- [x] 11.6 运行全部测试 → committed

## 12. 路由层集成 — Orchestrator 接管

- [x] 12.1 在 `routers/search.py` 用 Orchestrator 替换直接导入
- [x] 12.2 在 `routers/prediction.py` 用 Orchestrator 替换直接导入
- [x] 12.3 API 签名和响应格式完全不变
- [x] 12.4 运行全部 API 集成测试
- [x] 12.5 运行全部测试 → committed

## 13. DSPy 训练闭环接入

- [x] 13.1 TrajectoryLogger 记录所有执行 + 写入 TrajectoryStore
- [x] 13.2 `POST /api/admin/export-dspy-dataset`
- [x] 13.3 `POST /api/admin/optimize-prompt`
- [x] 13.4 优化成功后将变体注册到 PromptRegistry
- [x] 13.5 `GET /api/admin/prompt-variants/{name}`
- [x] 13.6 编写测试
- [x] 13.7 运行全部测试 → committed

## 14. 端到端验证 + 架构图更新

- [x] 14.1 端到端测试：多轮对话记忆保持、闲聊不死板
- [x] 14.2 端到端测试：Orchestrator → 动态 Planner → 自纠正
- [x] 14.3 端到端测试：DSPy 轨迹数据流 TrajectoryLogger → TrajectoryStore
- [ ] 14.4 更新 `项目架构图.html`
- [ ] 14.5 更新 openspec/specs/ 正式 spec 文件
- [ ] 14.6 最终 commit
