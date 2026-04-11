# 七项要求对照表

更新日期：2026-04-11

本附录把最终验收要求映射到系统实现、OpenSpec 章节与验证证据。

## 1. Effective

- 要求：不同角色使用专门化 agent，具备流程隔离
- 代码实现：
  - `backend/app/agents/base.py`
  - `backend/app/agents/pipeline.py`
  - `backend/app/agents/similar_case.py`
  - `backend/app/agents/contract_review.py`
  - `backend/app/agents/opponent_prediction.py`
  - `backend/app/agents/chat.py`
- OpenSpec 对应：
  - `specs/agent-framework/spec.md`
  - tasks `5.x`, `12.x`, `13.x`, `14.x`, `15.x`
- 验证证据：
  - `tests/test_agent_framework.py`
  - `tests/test_agent_similar_case.py`
  - `tests/test_agent_contract_review.py`
  - `tests/test_agent_opponent_prediction.py`
  - `tests/test_agent_chat.py`
  - `tests/test_agent_phase3_integration.py`

## 2. Efficient

- 要求：token 预算系统与缓存感知的 prompt 组装
- 代码实现：
  - `backend/app/services/analytics/token_budget.py`
  - `backend/app/prompts/registry.py`
- OpenSpec 对应：
  - `specs/token-budget/spec.md`
  - `specs/prompt-registry/spec.md`
  - tasks `3.x`, `4.x`, `17.x`
- 验证证据：
  - `tests/test_token_budget.py`
  - `tests/test_prompt_registry.py`
  - `tests/test_dspy_signatures.py`

## 3. Safe

- 要求：工具执行治理流程不可被模型绕过
- 代码实现：
  - `backend/app/agents/tool_governance.py`
  - `backend/app/agents/output_governance.py`
- OpenSpec 对应：
  - `specs/governance-pipeline/spec.md`
  - tasks `6.x`, `7.x`
- 验证证据：
  - `tests/test_tool_governance.py`
  - `tests/test_output_governance.py`
  - `tests/test_api_contract.py`

## 4. Robust

- 要求：支持脏状态清理、中断恢复、进程泄漏治理
- 代码实现：
  - `backend/app/services/robustness.py`
  - request cancellation / task tracking integration in pipeline and routers
- OpenSpec 对应：
  - `specs/checkpoint-resume/spec.md`
  - tasks `9.x`
- 验证证据：
  - `tests/test_robustness.py`

## 5. Monitorable

- 要求：集中式遥测服务，而不是零散 print
- 代码实现：
  - `backend/app/services/analytics/telemetry.py`
  - `backend/app/services/analytics/middleware.py`
- OpenSpec 对应：
  - tasks `2.x`
- 验证证据：
  - `tests/test_telemetry.py`

## 6. Updatable

- 要求：模块化 prompt 分段和可版本化 skills/behavior
- 代码实现：
  - `backend/app/prompts/*.yaml`
  - `backend/app/prompts/registry.py`
  - `backend/app/prompts/signatures.py`
  - `backend/app/prompts/optimization.py`
- OpenSpec 对应：
  - `specs/prompt-registry/spec.md`
  - tasks `3.x`, `17.x`
- 验证证据：
  - `tests/test_prompt_registry.py`
  - `tests/test_dspy_signatures.py`

## 7. Compounding

- 要求：系统层结构化轨迹，可进入训练闭环
- 代码实现：
  - `backend/app/services/trajectory/logger.py`
  - `backend/app/services/trajectory/store.py`
  - `backend/app/services/trajectory/replay.py`
  - `backend/app/routers/trajectory.py`
  - `backend/app/prompts/optimization.py`
- OpenSpec 对应：
  - `specs/trajectory-logging/spec.md`
  - tasks `11.x`, `17.x`
- 验证证据：
  - `tests/test_trajectory.py`
  - `tests/test_dspy_signatures.py`

## 前端测试补充

前端当前是原生静态实现，没有 `package.json` 与独立 JS test runner。最终验收采用以下可重复验证方式：

- `tests/test_frontend_static.py`
  - 静态资源存在性
  - `node --check frontend/app.js` 语法校验
  - HTML 应用骨架与关键 DOM 节点校验
  - 前后端路由装配校验
  - 响应式和无障碍相关样式约束校验
