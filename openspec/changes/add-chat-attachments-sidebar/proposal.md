## Why

当前主聊天输入区已经加入左下角上传入口，但普通聊天模式还不能把上传文件作为会话附件交给 AI 直接阅读，右侧栏也只能显示引用来源，无法查看当前会话已上传的附件。用户需要的是一种轻量的聊天附件能力，而不是把这些文件全部纳入知识库。

## What Changes

- 新增普通聊天模式下的会话级附件上传能力，允许用户通过聊天输入区左下角上传按钮添加一个或多个附件。
- 新增普通聊天附件参与主聊天回答的链路，使 AI 可以读取当前会话上传的附件内容。
- 将聊天右侧栏改造成带顶部标签页的侧栏，至少支持“附件”和“引用来源”两个标签页。
- 允许用户在右侧栏附件标签页中查看当前会话已上传的普通聊天附件。
- 明确区分普通聊天附件、合同审查待审合同、标准模板库和现有文件管理数据，避免混入同一条存储路径。

## Capabilities

### New Capabilities
- `chat-session-attachments`: 管理普通聊天模式下的会话级附件上传、展示、生命周期和 AI 可读性。
- `chat-right-sidebar-tabs`: 为主聊天右侧栏提供标签页切换，并承载附件列表与引用来源两类内容。

### Modified Capabilities
- None.

## Impact

- Affected code: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `backend/app/routers/search.py`, `backend/app/services/chat.py`，以及新的会话级聊天附件存储或解析模块。
- Affected APIs: 新增普通聊天附件上传或引用接口；主聊天请求需要接收附件引用并将其纳入回答上下文。
- Affected systems: 主聊天输入区、会话状态模型、右侧栏状态机、聊天回答上下文组装链路。
- Data impact: 普通聊天附件只作为会话级输入，不写入数据库、向量索引、标准模板库或文件管理列表。
- Product impact: 主聊天从“纯文本提问”升级为“文本 + 会话附件”的工作流，同时右侧栏从单一引用视图升级为多标签信息面板。
