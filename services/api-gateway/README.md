# API Gateway Service

企业级 AI 应用的 API 网关服务，基于 FastAPI 构建。

## 技术栈

- **Framework**: FastAPI 0.110+
- **Database**: PostgreSQL 16 + pgvector (向量检索)
- **ORM**: SQLAlchemy 2.0 + Alembic (迁移)
- **Cache/Queue**: Redis 7
- **Auth**: JWT (Access + Refresh Token) + RBAC
- **Monitoring**: Prometheus + OpenTelemetry + Structlog
- **API Docs**: Swagger UI + ReDoc

## 快速开始

### 1. 安装依赖

```bash
cd services/api-gateway
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入配置
```

关键配置：
- `DATABASE_URL` - PostgreSQL 连接字符串
- `REDIS_URL` - Redis 连接字符串
- `JWT_SECRET` - JWT 签名密钥 (生产环境必须 ≥64 字符)
- `OPENAI_API_KEY` - OpenAI API Key (用于 LLM 调用)

### 3. 运行数据库迁移

```bash
alembic upgrade head
```

### 4. 启动开发服务器

```bash
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/api/v1/openapi.json

## 项目结构

```
app/
├── api/
│   ├── v1/              # API v1 路由
│   │   ├── auth.py      # 认证 (登录、注册、Token 刷新)
│   │   ├── users.py     # 用户管理
│   │   ├── tenants.py   # 租户管理
│   │   ├── knowledge_bases.py  # 知识库
│   │   ├── documents.py  # 文档管理
│   │   ├── conversations.py  # 对话/聊天
│   │   ├── workflows.py  # 工作流编排
│   │   ├── models.py     # 模型配置
│   │   ├── audit_logs.py # 审计日志
│   │   ├── notifications.py # 通知
│   │   ├── costs.py      # 成本追踪
│   │   ├── system_configs.py # 系统配置
│   │   └── api_keys.py   # API Key 管理
│   └── internal.py      # 内部服务间调用 API
├── core/
│   ├── config.py        # 配置管理 (Pydantic Settings)
│   ├── security.py      # 认证授权核心 (JWT, 密码, 权限)
│   └── middleware.py    # 中间件 (日志、指标、限流、CORS、安全头)
├── db/
│   └── session.py       # 数据库会话管理
├── models/
│   └── __init__.py      # SQLAlchemy 模型 (16 个核心表)
├── schemas/
│   └── __init__.py      # Pydantic Schema (请求/响应验证)
├── services/            # 业务逻辑服务 (待实现)
└── main.py              # FastAPI 应用入口
```

## 核心功能

### 认证授权
- JWT Access Token (15min) + Refresh Token (7天)
- RBAC 角色: SUPER_ADMIN, ADMIN, MEMBER, VIEWER
- 多租户隔离
- API Key 服务间认证

### API 模块
| 模块 | 路径 | 核心功能 |
|------|------|----------|
| Auth | `/api/v1/auth` | 登录、注册、Token 刷新、登出、密码修改 |
| Users | `/api/v1/users` | 用户 CRUD、权限查看 |
| Tenants | `/api/v1/tenants` | 租户信息、设置管理 |
| Knowledge Bases | `/api/v1/knowledge-bases` | 知识库 CRUD、检索配置、统计 |
| Documents | `/api/v1/documents` | 文档上传/创建/管理、分块查看、重新处理 |
| Conversations | `/api/v1/conversations` | 对话管理、消息历史、流式/非流式聊天 |
| Workflows | `/api/v1/workflows` | 工作流 CRUD、发布/执行、执行历史 |
| Models | `/api/v1/models` | 模型列表、默认模型查询 |
| Audit Logs | `/api/v1/audit-logs` | 审计日志查询、导出 |
| Notifications | `/api/v1/notifications` | 通知列表、已读/删除、未读计数 |
| Costs | `/api/v1/costs` | 成本记录、汇总统计、Token 预算 |
| System Configs | `/api/v1/system-configs` | 系统配置管理 |
| API Keys | `/api/v1/api-keys` | API Key 创建/撤销 |

### 中间件栈 (执行顺序)
1. **ExceptionHandlerMiddleware** - 全局异常处理
2. **SecurityHeadersMiddleware** - 安全头 (CSP, HSTS, X-Frame-Options 等)
3. **CORSMiddleware** - 跨域配置
4. **ServiceAuthMiddleware** - 内部服务认证
5. **RateLimitMiddleware** - Redis 滑动窗口限流
6. **MetricsMiddleware** - Prometheus 指标收集
7. **RequestLoggingMiddleware** - 结构化请求日志

## 数据库模型 (16 表)

| 表 | 说明 |
|----|------|
| `tenants` | 租户/组织 |
| `users` | 用户 |
| `knowledge_bases` | 知识库 |
| `documents` | 文档 |
| `document_chunks` | 文档分块 (含向量) |
| `conversations` | 对话 |
| `messages` | 消息 |
| `workflows` | 工作流定义 |
| `workflow_executions` | 工作流执行记录 |
| `models` | 模型配置 |
| `audit_logs` | 审计日志 |
| `notifications` | 通知 |
| `cost_records` | 成本记录 |
| `token_budgets` | Token 预算 |
| `system_configs` | 系统配置 |
| `refresh_tokens` | 刷新 Token |
| `api_keys` | API Key |

## 开发指南

### 添加新路由

1. 在 `app/api/v1/` 创建新文件 `new_module.py`
2. 定义 router: `router = APIRouter(prefix="/new-module", tags=["New Module"])`
3. 在 `app/api/v1/__init__.py` 导出
4. 在 `app/main.py` 注册: `app.include_router(new_module.router, prefix=settings.API_PREFIX)`

### 运行测试

```bash
pytest tests/ -v --cov=app
```

### 代码检查

```bash
ruff check app/
mypy app/
```

### 生成新迁移

```bash
alembic revision --autogenerate -m "描述变更"
alembic upgrade head
```

## 部署

### Docker

```bash
docker build -f ../../infra/docker/api-gateway/Dockerfile -t enterprise-ai/api-gateway .
docker run -p 8000:8000 --env-file .env enterprise-ai/api-gateway
```

### Kubernetes

参考 `infra/k8s/` 下的 Helm Charts / Kustomize 配置。

## 环境变量参考

见项目根目录 `.env.example`。

## 监控指标

- `http_requests_total` - 请求总数 (method, endpoint, status)
- `http_request_duration_seconds` - 请求延迟直方图
- `http_requests_in_progress` - 进行中请求数
- `rate_limit_exceeded_total` - 限流触发次数

## 许可证

MIT