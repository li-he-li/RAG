# RAG Legal Similarity Search

法律文书相似检索与证据溯源系统。项目包含 FastAPI 后端、原生静态前端，以及用于评估检索质量的离线脚本。

## Structure

- `backend/`: FastAPI 服务、向量检索、文档入库、评估脚本
- `frontend/`: 聊天式检索前端
- `openspec/`: 需求、设计、任务拆解
- `启动说明.md`: 本地中文启动说明
- `项目架构图.html`: 架构总览图

## Current Frontend

- 主聊天窗口支持数据库证据支撑的流式回答。
- 回答中的“引用来源”会在聊天区右侧展开独立侧栏，支持关闭和桌面端拖拽调宽。
- 左侧栏包含“合同审查”入口，当前用于标准模板相关能力的前端入口预留。

## Environment

- Python 3.12
- Docker Desktop
- PostgreSQL 容器 `legal-search-postgres`
- Qdrant 容器 `legal-search-qdrant`

模型缓存目录是 `backend/data/models_cache/`，属于运行产物，不纳入版本控制。

## Setup

1. 安装后端依赖：

```powershell
cd backend
pip install -r requirements.txt
```

2. 复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

3. 启动 Docker Desktop，并确保 PostgreSQL 与 Qdrant 可访问。

4. 启动后端：

```powershell
cd backend
D:\Anaconda\envs\legal-search\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

5. 启动前端静态页：

```powershell
D:\Anaconda\python.exe -m http.server 3000 --bind 127.0.0.1 --directory frontend
```

## Git Hooks

仓库内提供 `.githooks/`，包含 `pre-commit`、`pre-push`、`commit-msg`。

启用方式：

```powershell
git config core.hooksPath .githooks
```

Hook 说明：

- `pre-commit`: 仅检查已暂存文件，阻止提交 `.env`、模型缓存、日志、`__pycache__` 等垃圾文件，并对暂存的 Python/JSON 文件做语法校验。
- `pre-push`: 对仓库内 Python 文件做全量语法校验，校验 JSON/JSONL 文件结构，并确认 README 中包含 hook 使用说明。
- `commit-msg`: 校验 conventional commit，允许的类型为 `feat`、`fix`、`docs`、`style`、`refactor`、`test`、`chore`、`perf`、`ci`、`build`、`revert`。

必要时可用 `--no-verify` 跳过 hook，但仅适合紧急情况，正常开发不应依赖。

## Validation

本仓库目前没有完整自动化测试套件。提交前至少执行：

```powershell
python scripts/hook_checks.py pre-push
```

如果你需要验证运行链路，再额外检查：

- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:3000/index.html`

## Notes

- `backend/.env` 不纳入版本控制。
- `backend/data/models_cache/`、日志文件、解释器缓存属于本地运行产物。
- 当前前端依赖后端 `http://localhost:8000/api`。

## Recent Updates (2026-04)

- Chat composer now supports a shared upload entry that routes by mode:
  - `chat` mode uploads session attachments for normal conversation.
  - `contract-review` mode uploads review-target contracts.
- The left `合同审查` panel is now a standard template library:
  - Templates are uploaded, listed, and deleted through the dedicated left-side panel.
  - Template management is separate from session attachments and review-target files.
- The right sidebar is now tabbed (`Attachments` / `Citations`) and remains hidden by default.
  - It opens when attachments are uploaded or when citation sources are clicked.
  - Users can close the sidebar manually at any time.
- Contract review behavior is updated in OpenSpec:
  - Review requests are allowed even without uploaded contracts.
  - Backend should return an explicit "no contract available for review" result.

## Latest Behavior (2026-04-05)

- Contract review now waits for the user to send a review request before template matching starts.
- Template matching runs first through `GET /contract-review/template-recommendation`.
- The matched template options are rendered in the main chat stream instead of a separate area below the composer.
- Review generation starts only after the user clicks a template option, then streams through `POST /contract-review/stream`.
- The attachment tray now sits above the composer and shows removable session files across normal chat and contract-review mode.
- Session temp uploads use `/session-files/upload`, `/session-files`, and `/session-files/{file_id}` and stay outside the persistent template/document library.
- In normal chat mode, session `chat_attachment` files can now drive similar-case retrieval and are also passed into answer generation context for case-to-case similarity reasoning.
