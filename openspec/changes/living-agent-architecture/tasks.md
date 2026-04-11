## 1. 记忆存储层 — ConversationMessage 模型与持久化

- [x] 1.1 创建 SQLAlchemy 模型 `ConversationMessage`（id, session_id, role, content, token_count, created_at, metadata）
- [ ] 1.2 创建 Alembic migration 文件新增 `conversation_messages` 表 + 索引 `idx_conv_msg_session_created`
- [x] 1.3 创建 `app/services/memory/store.py`：`save_message()`, `load_messages(session_id, limit)`, `delete_session(session_id)`, `cleanup_old_sessions(max_age_hours=24)`
- [x] 1.4 编写测试：消息 CRUD、按 session 查询有序、cleanup 只删旧 session
- [ ] 1.5 运行全部测试 → commit: `feat(memory): add ConversationMessage model and persistence`

## 2. Token 预算感知的上下文组装

- [x] 2.1 创建 `app/services/memory/context_assembler.py`：`assemble_context(session_id, system_prompt, current_message, token_budget) -> list[dict]`
- [x] 2.2 实现 token 预算计算：从 ConversationMessage 加载最近消息，累加 token_count，在预算内截断
- [x] 2.3 实现 auto-compact：当旧消息被截断时，调用 LLM 生成摘要，存储为 role=system, metadata.type=compact_summary 的特殊消息
- [x] 2.4 组装最终 messages 数组：`[system_prompt, summary(如有), ...历史消息, 当前用户消息]`
- [x] 2.5 编写测试：首条消息无历史、多轮对话完整加载、超预算触发摘要、摘要保留关键信息
- [ ] 2.6 运行全部测试 → commit: `feat(memory): add token-budget-aware context assembly with auto-compact`

## 3. Chat 服务接入记忆 — 多轮对话

- [ ] 3.1 重构 `app/services/chat.py` 的 `_build_deepseek_payload()`：接收 messages 数组而非单条 user_message
- [ ] 3.2 在 `execute_grounded_chat()` 和 `stream_grounded_chat()` 中：保存用户消息 → 组装上下文 → 调用 LLM → 保存助手响应
- [ ] 3.3 确保 grounded 模式下 messages 格式：`[system_prompt+证据上下文, ...历史消息, 当前用户消息]`
- [ ] 3.4 确保非 grounded 模式下 messages 格式：`[system_prompt, ...历史消息, 当前用户消息]`
- [x] 3.5 编写测试：多轮对话上下文正确传递、grounded 证据+历史消息共存
- [ ] 3.6 运行全部测试 → commit: `feat(memory): integrate conversation memory into chat service`

## 4. 闲聊记忆路径 — 不死板

- [ ] 4.1 扩展 `_should_skip_retrieval()` 添加更多闲聊模式（总结上文、追问、闲聊追问等）
- [ ] 4.2 实现 `_handle_casual_chat()`：组装 `[casual_system_prompt, ...历史消息, 当前消息]`，直接调 DeepSeek 不走检索
- [ ] 4.3 casual_system_prompt 设计：友好风格，说明自己是法律助手，可以闲聊也可以回答法律问题
- [x] 4.4 编写测试：闲聊不触发检索、上下文引用正确、法律问题仍走检索
- [ ] 4.5 运行全部测试 → commit: `feat(memory): add casual chat path with conversation history`

## 5. AgentBase 扩展 — can_handle + ValidationRule

- [x] 5.1 在 `AgentBase` 中新增 `can_handle(input) -> float` 方法，默认返回 0.0
- [ ] 5.2 为 4 个现有 Agent 实现 `can_handle()`：根据 payload 字段和 endpoint 路径返回置信度
- [x] 5.3 新增 `ValidationRule` 协议类：`check(output) -> Pass | Fail(reason, retryable)`
- [ ] 5.4 为现有 4 个 Validator 各实现至少 2 条 ValidationRule（schema 校验 + 业务规则）
- [x] 5.5 编写测试：can_handle 置信度、ValidationRule 链通过/拒绝
- [ ] 5.6 运行全部测试 → commit: `feat(agents): add can_handle and ValidationRule to AgentBase`

## 6. ExecutionPlan 扩展 — 条件分支

- [x] 6.1 在 `PlanStep` 中新增 `condition: str | None` 字段（Python eval 表达式）
- [x] 6.2 在 `PlanStep` 中新增 `parallel_group: str | None` 字段（Phase 2 预留）
- [x] 6.3 在 `AgentPipeline` 中实现条件评估：执行前检查 condition，True 则执行，否则跳过
- [x] 6.4 编写测试：条件分支执行/跳过
- [ ] 6.5 运行全部测试 → commit: `feat(agents): add conditional branches to ExecutionPlan`

## 7. PlanningStrategy — 动态规划

- [x] 7.1 定义 `PlanningStrategy` 协议：`select_strategy(input) -> str`, `build_plan(input, strategy) -> ExecutionPlan`
- [ ] 7.2 为 ContractReviewPlanner 实现 3 种策略：simple_review / complex_review / cross_reference_review
- [ ] 7.3 为 PredictionPlanner 实现 2 种策略：direct_prediction / evidence_backed_prediction
- [x] 7.4 编写测试：不同输入触发不同策略、计划步骤数不同
- [ ] 7.5 运行全部测试 → commit: `feat(agents): implement PlanningStrategy for dynamic plan generation`

## 8. 自纠正循环

- [x] 8.1 在 `AgentPipeline` 中新增 `max_retries: int = 2` 参数
- [x] 8.2 修改 `run()`：Validator 返回 Rejection → 检查有 Planner + retryable + 未耗尽 → 重新规划
- [x] 8.3 将 Rejection 传回 Planner 生成新 ExecutionPlan
- [x] 8.4 非 retryable 错误直接返回，无 Planner 不触发重试
- [x] 8.5 编写测试：重试成功、重试耗尽、非 retryable 跳过
- [ ] 8.6 运行全部测试 → commit: `feat(agents): add self-correction loop to AgentPipeline`

## 9. Agent-as-Tool 注册 + 递归防护

- [ ] 9.1 新增 `AgentTool` 包装类：将 Agent.execute() 暴露为工具函数，自动注入 recursion_depth
- [ ] 9.2 将 4 个 Agent 注册为 Tool（side_effect_level=READ_ONLY）
- [ ] 9.3 ToolGovernancePolicy 新增 max_recursion_depth=3，超限 block
- [ ] 9.4 编写测试：AgentTool 包装、通过 invoke_tool 调用、递归超限 block
- [ ] 9.5 运行全部测试 → commit: `feat(agents): add Agent-as-Tool with recursion protection`

## 10. Agent 间协作 — 业务层启用

- [ ] 10.1 ContractReviewExecutor 复杂策略中增加可选步骤调用 similar_case_search 工具
- [ ] 10.2 PredictionExecutor evidence_backed 策略中调用 retrieval 工具获取佐证
- [ ] 10.3 输出结构扩展包含 cross_references 字段
- [ ] 10.4 编写测试：Agent A 成功调用 Agent B、结果合并
- [ ] 10.5 运行全部测试 → commit: `feat(agents): enable cross-agent collaboration`

## 11. Orchestrator Agent

- [ ] 11.1 实现 `IntentRouter`：基于 endpoint path + payload 字段的确定性规则映射
- [ ] 11.2 实现 `OrchestratorAgent`：classify → SkillRegistry.discover → execute pipeline → return
- [ ] 11.3 覆盖全部现有路由的 intent 规则
- [ ] 11.4 未知 intent fallback 到 Chat + 遥测
- [ ] 11.5 编写测试：每种 intent 正确路由、fallback、SkillNotFoundError
- [ ] 11.6 运行全部测试 → commit: `feat(agents): implement OrchestratorAgent with IntentRouter`

## 12. 路由层集成 — Orchestrator 接管

- [ ] 12.1 在 `routers/search.py` 用 Orchestrator 替换 if-else
- [ ] 12.2 在 `routers/prediction.py` 用 Orchestrator 替换 if-else
- [ ] 12.3 API 签名和响应格式完全不变
- [ ] 12.4 运行全部 API 集成测试
- [ ] 12.5 运行全部测试 → commit: `refactor(routers): replace hardcoded routing with OrchestratorAgent`

## 13. DSPy 训练闭环接入

- [ ] 13.1 确保 TrajectoryLogger 记录所有 AgentPipeline 执行的 input/output/prompt_versions
- [ ] 13.2 新增 `POST /api/admin/export-dspy-dataset`：调用 `export_trajectory_evalset()` 导出轨迹数据
- [ ] 13.3 新增 `POST /api/admin/optimize-prompt`：触发 `optimize_prompt_module()`，返回 validation_score
- [ ] 13.4 优化成功后将变体注册到 PromptRegistry（带版本后缀）
- [ ] 13.5 新增 `GET /api/admin/prompt-variants/{name}` 和 `PUT .../activate`：列出和切换 prompt 变体
- [ ] 13.6 编写测试：轨迹导出、优化触发、变体注册、变体切换
- [ ] 13.7 运行全部测试 → commit: `feat(dspy): integrate DSPy optimization into production pipeline`

## 14. 端到端验证 + 架构图更新

- [ ] 14.1 端到端测试：多轮对话记忆保持、闲聊不死板、法律检索+历史上下文共存
- [ ] 14.2 端到端测试：Orchestrator → 动态 Planner → Agent 协作 → 自纠正 → 响应
- [ ] 14.3 端到端测试：DSPy 轨迹导出 → 优化 → 变体发布
- [ ] 14.4 更新 `项目架构图.html`：反映记忆层、Orchestrator、Agent 间调用、DSPy 闭环
- [ ] 14.5 更新 openspec/specs/ 正式 spec 文件
- [ ] 14.6 运行全部测试 → commit: `feat: living agent architecture with memory and DSPy loop complete`
