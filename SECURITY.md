# 安全说明与部署清单

本文档记录本仓库已实施的安全加固及生产环境建议。更新安全相关行为时请同步修改本节。

## 已实施措施（代码）

| 项目 | 说明 |
|------|------|
| **第三方密钥** | `DEEPSEEK_API_KEY` 在代码中**无默认值**，须通过环境变量或 `backend/.env` 配置；切勿将真实密钥提交到 Git。 |
| **CORS** | 默认仅允许常见本机前端 Origin（见下文环境变量）。`CORS_ALLOW_ORIGINS=*` 时自动关闭 `allow_credentials`，避免与规范冲突。 |
| **可选 API 密钥** | 设置环境变量 `API_KEY` 后，所有 `/api/*` 请求须带请求头 `X-API-Key` 或 `Authorization: Bearer <key>`（`OPTIONS` 预检除外）。 |
| **上传大小** | 单次上传由 `MAX_UPLOAD_BYTES` 限制（默认 50 MiB），超限返回 HTTP 413。 |
| **会话 ID** | 前端新建会话使用 `crypto.randomUUID()`（不可用时回退为更长随机串），降低会话标识被猜中概率。 |
| **前端与 API 密钥** | 静态页可通过 `localStorage.setItem("apiKeyOverride", "<与后端一致的密钥>")` 配合后端 `API_KEY`（仅适用于可信环境）。 |
| **错误脱敏** | `DEBUG=false`（默认）时，通用 500 响应不返回异常原文；解析类错误不暴露路径。排障可临时设 `DEBUG=true`。 |
| **HTTP 安全头** | 统一附加 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`。 |
| **限流** | `RATE_LIMIT_PER_MINUTE`（默认 120，0 关闭）对 `/api/*` 按客户端 IP 做约 60 秒滑动窗口限制；单机内存实现，多实例需网关层限流。 |
| **JSON 体大小** | `MAX_JSON_BODY_BYTES`（默认 8 MiB）基于 `Content-Length` 拒绝过大非 `multipart` 请求。 |
| **Host 校验** | 设置 `TRUSTED_HOSTS`（逗号分隔）时启用 `TrustedHostMiddleware`；留空则不校验（开发默认）。 |
| **弱口令提示** | 若 `PG_PASSWORD` 仍为默认 `legalsearch`，启动时写 WARNING 日志。 |
| **上游日志** | `DEBUG=false` 时 DeepSeek 失败日志不打印响应体片段，避免泄露。 |

## 环境变量（`backend/.env`）

复制 `backend/.env.example` 为 `backend/.env` 后按需填写。

| 变量 | 含义 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥；留空则对话等功能走本地降级逻辑。 |
| `GOOGLE_API_KEY` | 使用 Google 嵌入模型时必填。 |
| `API_KEY` | 非空则启用对 `/api/*` 的共享密钥校验。 |
| `CORS_ALLOW_ORIGINS` | 逗号分隔的 Origin 列表，例如 `https://app.example.com`。留空则使用开发用默认本机列表。设为 `*` 表示任意来源（此时不会携带 credentials）。 |
| `CORS_ALLOW_CREDENTIALS` | `true`/`false`，在显式 Origin 列表下是否允许携带凭证类 Cookie；与 `*` 勿混用。 |
| `MAX_UPLOAD_BYTES` | 单次上传最大字节数。 |
| `DEBUG` | `true` 时在客户端可见错误中带异常详情；生产务必为 `false` 或不设置。 |
| `RATE_LIMIT_PER_MINUTE` | `/api/*` 每 IP 每分钟最大请求数；`0` 关闭。 |
| `MAX_JSON_BODY_BYTES` | JSON/NDJSON 等非 multipart 请求体最大字节数。 |
| `TRUSTED_HOSTS` | 非空则仅允许这些 `Host`（逗号分隔，如 `localhost,127.0.0.1,app.example.com`）。 |
| `PG_PASSWORD` | PostgreSQL 密码；生产环境**必须**改为强口令并限制网络访问。 |

### 从 `file://` 打开本地 HTML

浏览器 Origin 为字符串 `null`。若需跨域访问本机 API，在 `CORS_ALLOW_ORIGINS` 中加入 `null`（仍建议通过本地 HTTP 静态服务打开前端以降低风险）。

## 生产环境建议

1. **网络**：`SERVER_HOST` 仅监听 `127.0.0.1`，由 Nginx/Caddy 等对外提供 **HTTPS**，并限制管理端口暴露。
2. **数据库与向量库**：PostgreSQL、Qdrant 仅对应用网段开放；为 Qdrant 启用 API Key、为 Postgres 使用 TLS。
3. **依赖**：锁定依赖版本并定期执行 `pip-audit` / `safety check`。
4. **密钥轮换**：若历史提交中曾包含真实 API 密钥，应在服务商控制台**作废并轮换**，必要时清理 Git 历史。
5. **日志与错误**：避免在对外错误信息中返回堆栈或内部路径；详细异常仅写服务端日志。

## 变更记录

- **2026-04-09（续）**：`DEBUG` 与 `internal_error_detail` 脱敏；安全响应头；`/api` 限流；JSON 体上限；可选 `TRUSTED_HOSTS`；默认 PG 口令告警；DeepSeek 错误日志脱敏。
- **2026-04-09**：移除默认 DeepSeek 密钥；收紧 CORS；可选 `API_KEY`；上传大小限制；会话 ID 使用 UUID；前端 `apiFetch` + `apiKeyOverride`；本文档初稿。
