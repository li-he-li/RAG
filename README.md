# RAG Legal Similarity Search

法律文书相似检索、证据溯源与法律工作流实验项目。

## Repository Layout

- `backend/`: FastAPI 后端、检索与各业务链路
- `frontend/`: 原生静态前端
- `docs/`: 用户手册与说明文档
- `scripts/`: 启动脚本与仓库检查脚本

## Core Capabilities

1. 普通聊天检索
- 基于数据库证据检索并回答
- 支持会话附件参与检索
- 回答展示引用来源与命中文件名

2. 合同审查
- 支持标准模板管理
- 支持待审合同上传与流式审查

3. 观点预测
- 支持案件模板管理（案情材料/对方语料）
- 支持模板选择后的独立预测链路

4. 类案检索
- 独立 `similar-case` 模式
- 返回同案、高相似、普通类案分层结果

## Local Run

### 1) Install Dependencies

```powershell
cd backend
pip install -r requirements.txt
```

### 2) Configure Environment

```powershell
cd backend
Copy-Item .env.example .env
```

### 3) Start Backend

```powershell
cd backend
D:\Anaconda\envs\legal-search\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4) Start Frontend

```powershell
D:\Anaconda\python.exe -m http.server 3000 --bind 127.0.0.1 --directory frontend
```

### 5) Verify

- Backend health: `http://127.0.0.1:8000/api/health`
- Frontend page: `http://127.0.0.1:3000/index.html`

## Security

部署、CORS、`API_KEY`、上传限制与密钥管理见 [SECURITY.md](./SECURITY.md)。

## Git Hooks

仓库使用 `.githooks/`:
- `pre-commit`
- `pre-push`
- `commit-msg`

启用命令：

```powershell
git config core.hooksPath .githooks
```

Hook 行为：
- `pre-commit`: 仅检查已暂存文件，阻止提交缓存/模型/日志等垃圾文件，检查 Python/JSON 语法，并校验注释语言统一为英文
- `pre-push`: 全仓 Python 语法检查、JSON/JSONL 校验、README hook 文档校验，并校验注释语言统一为英文
- `commit-msg`: conventional commit 校验

紧急情况下可使用 `--no-verify` 跳过 hook（不建议常用）。

## Pre-Submission Checks

```powershell
python scripts/hook_checks.py pre-commit
python scripts/hook_checks.py pre-push
node --check frontend/app.js
```

## Keep Out of Git

以下内容为本地运行产物，不应提交：
- `backend/data/models_cache/`
- `backend/.env`
- `.tmp/`
- 日志文件
- `__pycache__/`

## Recent Updates

### 2026-04-07

- 普通聊天链路增强：答案顶部强制展示数据库命中的 PDF 文件名（来自 `citations.file_name`），并保持回答围绕用户问题。
- 普通聊天检索增强：默认文档召回数量提升到 8；当附件聚焦检索未命中时，自动回退到原始用户问题再检索一次，降低漏召回。
- 移动端适配：新增左侧栏遮罩层，点击左侧栏外区域可收起左侧栏；在移动端点击新对话、菜单项、历史会话后也会自动收起左侧栏。
