# RAG Legal Similarity Search

法律文书相似检索与证据溯源系统。项目包含 FastAPI 后端、原生静态前端，以及用于评估检索质量的离线脚本。

## Structure

- `backend/`: FastAPI 服务、向量检索、文档入库、评估脚本
- `frontend/`: 聊天式检索前端
- `openspec/`: 需求、设计、任务拆解
- `启动说明.md`: 本地中文启动说明
- `项目架构图.html`: 架构总览图

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
