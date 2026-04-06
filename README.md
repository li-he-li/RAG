# RAG Legal Similarity Search

法律文书相似检索、证据溯源与法律工作流实验项目。当前项目包含三条主要能力链路：

- 普通聊天检索
- 合同审查
- 对方观点预测

## 项目结构

- `backend/`
  FastAPI 后端、检索、文档入库、模板管理、预测链路
- `frontend/`
  原生静态前端
- `openspec/`
  需求、设计、任务拆解
- `启动说明.md`
  本地中文启动说明
- `项目架构图.html`
  架构示意

## 当前功能

### 1. 普通聊天检索

- 基于数据库证据进行相似检索和回答
- 支持会话级附件上传
- 支持引用来源侧栏查看

### 2. 合同审查

- 左侧面板管理标准模板
- 聊天区先发问题，再在主聊天流中选择模板
- 支持审查目标合同上传
- 模板推荐通过 `/api/contract-review/template-recommendation`
- 审查生成通过 `/api/contract-review/stream`

### 3. 对方观点预测

- 独立的 `opponent-prediction` 模式
- 左侧 `观点预测` 面板用于管理案件模板
- 案件模板包含：
  - `案件名称` 必填
  - `案情材料` 必填
  - `对方语料` 选填
- 聊天区先发送自然语言问题，再在主聊天流中选择案件模板
- 预测链路独立于普通聊天和合同审查
- 当前预测链路包含：
  - 问题理解
  - 案件画像重构
  - 对方视角检索
  - 对方观点生成
  - 对方口吻生成
  - 我方应对建议
- 报告结果支持：
  - 动态标题
  - `对方可能会这样表述`
  - `主打 / 次打 / 补充`
  - 引用支持项与推断项区分

## 环境要求

- Python 3.12
- Docker Desktop
- PostgreSQL 容器：`legal-search-postgres`
- Qdrant 容器：`legal-search-qdrant`

以下内容属于本地运行产物，不应提交：

- `backend/data/models_cache/`
- `backend/.env`
- `.tmp/`
- 日志文件
- `__pycache__/`

## 本地启动

### 1. 安装依赖

```powershell
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

```powershell
cd backend
Copy-Item .env.example .env
```

然后按实际情况填写 `backend/.env`。

### 3. 启动后端

```powershell
cd backend
D:\Anaconda\envs\legal-search\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4. 启动前端

```powershell
D:\Anaconda\python.exe -m http.server 3000 --bind 127.0.0.1 --directory frontend
```

### 5. 验证

- 后端健康检查：`http://127.0.0.1:8000/api/health`
- 前端页面：`http://127.0.0.1:3000/index.html`

## 前端与 API

- 前端默认按当前页面主机解析后端地址：`http://<current-host>:8000/api`
- 可通过 `localStorage.apiBaseOverride` 覆盖 API 基地址

## 观点预测相关说明

### 案件模板存储

- 观点预测模板不会进入主检索文档库 `documents / paragraphs`
- 观点预测使用独立的数据表和服务
- 删除策略为硬删除

### 对方语料的作用

- 对方语料会参与案件画像重构
- 会影响对方有利点提取、检索 query 构造、观点排序和对方口吻生成
- 对方语料越接近真实答辩口径，预测结果越贴近真实对方表达

### 案件画像

当前案件画像不是简单硬编码结论，而是：

- 规则层先做候选线索收集
- LLM 再基于候选线索和精选片段做结构化重构
- LLM 失败时才回退到保守候选结果

## Git Hooks

仓库已提供 `.githooks/`：

- `pre-commit`
- `pre-push`
- `commit-msg`

启用方式：

```powershell
git config core.hooksPath .githooks
```

### Hook 行为

- `pre-commit`
  只检查已暂存文件，阻止提交 `.env`、模型缓存、日志、`__pycache__` 等垃圾文件，并校验 Python / JSON 基本语法
- `pre-push`
  对仓库内 Python 文件做全量语法检查，校验 JSON/JSONL，并确认 README 中包含 hook 说明
- `commit-msg`
  校验 conventional commit，允许的类型包括：
  - `feat`
  - `fix`
  - `docs`
  - `style`
  - `refactor`
  - `test`
  - `chore`
  - `perf`
  - `ci`
  - `build`
  - `revert`

必要时可以使用 `--no-verify` 跳过 hook，但只适合紧急情况。

## 提交前最少校验

```powershell
python scripts/hook_checks.py pre-commit
python scripts/hook_checks.py pre-push
```

如果改了前端主脚本，建议再跑：

```powershell
node --check frontend/app.js
```

## 最近更新

### 2026-04-05

- 合同审查改成“先发问题，再在主聊天流中选模板”
- 审查目标合同走会话级临时文件，不进入标准模板库
- 普通聊天附件可参与相似检索和回答上下文

### 2026-04-06

- 新增对方观点预测模式
- 新增案件模板管理
- 新增观点预测独立后端链路
- 新增对方口吻输出
- 新增问题驱动型结果重排
- 新增案件画像重构流程
