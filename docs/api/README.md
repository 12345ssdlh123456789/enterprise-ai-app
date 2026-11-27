# API 说明

交互式文档：`http://127.0.0.1:8000/docs`
OpenAPI JSON：`http://127.0.0.1:8000/api/v1/openapi.json`（注意在 `/api/v1` 前缀下）

## 认证

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email": "admin@example.com", "password": "admin123", "remember_me": true}
```

返回：

```json
{
  "success": true,
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 900,
    "user": { "id": "...", "email": "...", "role": "SUPER_ADMIN", "tenant_id": "..." }
  },
  "meta": { "request_id": "...", "timestamp": "...", "version": "0.1.0" }
}
```

之后所有请求带 `Authorization: Bearer <access_token>`。访问令牌 15 分钟过期，用 `POST /api/v1/auth/refresh` 换新。

## 响应包络

成功：`{"success": true, "data": <payload>, "meta": {...}}`
失败：`{"success": false, "error": {"code": "...", "message": "...", "details": {}}}`

分页接口的 `data` 为 `{items, total, page, page_size, total_pages}`，查询参数 `page`、`page_size`（**上限 100**）。个别接口（如 `/tenants`）直接返回数组。

## 主要端点

| 分组 | 端点 | 说明 |
|---|---|---|
| 健康 | `GET /health`、`/health/live`、`/health/ready` | 存活/就绪探针（不带 `/api/v1`） |
| 认证 | `/auth/login`、`/auth/refresh`、`/auth/logout`、`/auth/me`、`/auth/change-password` | JWT |
| 用户 | `GET/POST /users`、`GET/PATCH/DELETE /users/{id}`、`GET /users/me/permissions` | 租户内账号与角色 |
| 租户 | `GET/POST /tenants`、`GET/PATCH /tenants/me`、`PATCH /tenants/{id}` | 多租户 |
| 知识库 | `GET/POST /knowledge-bases`、`/knowledge-bases/{id}/stats` | RAG 容器 |
| 文档 | `POST /documents/upload`、`GET /documents`、`/documents/{id}/chunks`、`/documents/{id}/reprocess` | 解析与分块 |
| 对话 | `GET/POST /conversations`、`POST /conversations/chat/completions`、`/conversations/{id}/messages` | 支持流式 |
| 检索 | `POST /retrieval/search` | 向量 / 混合检索 |
| 工作流 | `GET/POST /workflows`、`/workflows/{id}/publish`、`/workflows/{id}/execute` | 编排与执行 |
| 模型 | `GET /models`、`GET /models/defaults/chat`、`PATCH /models/{id}` | `PATCH` 仅管理员，可启用/停用 |
| 成本 | `GET /costs/summary`、`/costs/records`、`/costs/budget` | 成本、用量、预算 |
| 审计 | `GET /audit-logs`、`/audit-logs/export`、`/audit-logs/resource/{type}/{id}` | 只读 |
| 系统配置 | `GET/PATCH /system-configs/{key}` | 租户级配置 |
| 内部 | `/internal/*` | 服务间调用，需 Service API Key |

## 错误码约定

| HTTP | 场景 |
|---|---|
| 400 | 参数语义错误（如非法分页） |
| 401 | 未登录 / Token 过期 / 密码错误 |
| 403 | 角色或租户越权 |
| 404 | 资源不存在或不属于当前租户 |
| 409 | 冲突（重复邮箱、重复 slug） |
| 422 | 请求体校验失败（Pydantic） |
| 429 | 触发限流或租户 token 预算 |

## 示例

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"admin123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")

curl -s http://127.0.0.1:8000/api/v1/models -H "Authorization: Bearer $TOKEN"
curl -s -X PATCH http://127.0.0.1:8000/api/v1/models/<model_id> \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```
