## Why

当前项目已经具备类案检索、证据溯源、聊天模式切换和会话附件能力，但还缺少一个专门面向法律攻防分析的“对方观点预测”工作流。仅靠普通聊天提示词无法稳定承载“自然语言问题 + 案件背景模板 + 可溯源依据 + 结构化预测报告”这类长链路能力，因此需要新增独立模式，并补齐案件模板管理与预测报告输出。

## What Changes

- 新增左侧“观点预测”页面，作为案件模板的后台管理入口，仅负责上传、保存、列表展示和删除。
- 新增案件模板模型：模板必须包含案件名称和至少一份案情材料，可选包含对方语料；模板保存后可在聊天区复用。
- 新增聊天区“观点预测”模式开关，交互方式对齐现有合同审查模式。
- 在观点预测模式下新增模板选择器，用户必须结合自然语言输入和所选模板发起预测任务。
- 新增观点预测后端链路：案件画像抽取、对方立场检索、观点树生成、我方反制层生成、预测报告卡片返回。
- 新增观点预测域独立数据表，避免将案件模板材料混入现有主检索文档库。
- 删除策略直接采用硬删除，并同步清理模板关联材料、切段结果和相关结果快照。

## Capabilities

### New Capabilities
- `opponent-prediction-templates`: 管理可复用的案件模板，支持案件名称、案情材料和可选对方语料的创建、列表和删除。
- `opponent-prediction-mode`: 在聊天区选择案件模板并结合自然语言问题，生成对方观点预测报告和我方反制建议。

### Modified Capabilities

## Impact

- Affected frontend: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
- Affected backend: `backend/app/models`, `backend/app/routers/search.py`, `backend/app/services`
- Affected APIs: 新增案件模板管理接口和观点预测任务接口
- Affected database: 新增观点预测域模板、材料、段落和报告相关表
- Affected UX: 新增左侧模板管理页、聊天区模板选择器、观点预测模式按钮和预测报告卡片
