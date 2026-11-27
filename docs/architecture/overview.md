# 架构总览

## 一句话

一个可本地运行的企业级 AI 应用骨架：API 网关（FastAPI）+ Web 工作台（Next.js）+ 管理后台（Next.js）+ SQLite/pgvector，覆盖多租户、RBAC、知识库 RAG、对话、工作流、成本与审计。

## 运行拓扑（本地开发）

```
浏览器
  ├── Web   http://localhost:3002   Next.js 14 App Router（知识库 / 对话 / 工作流）
  └── Admin http://localhost:3001   Next.js 14 App Router（总览 / 用户 / 租户 / 模型 / 审计 / 成本）
        │
        ▼
  API Gateway http://127.0.0.1:8000  FastAPI
        │  /api/v1/*        业务接口（JWT Bearer）
        │  /api/v1/openapi.json  OpenAPI 3.1
        │  /health /health/live /health/ready
        ▼
  SQLite（默认 ./data/enterprise_ai.db，创建表 + 演示数据）
  Redis（可选，用于限流/缓存）
  模型供应商：OpenAI / Anthropic / Azure / Ollama / vLLM
```

生产形态见 `docker-compose.yml` 与 `infra/k8s`：网关 + Web + Admin + PostgreSQL(pgvector) + Redis + MinIO + Prometheus/Grafana/Jaeger。
k8s 清单的权威版本是 `infra/k8s/base` + `overlays/{dev,staging,prod}`（ArgoCD 指的就是 overlay，`infra/k8s/helm` 那套 chart 未被使用），
其中 PostgreSQL / Redis / MinIO 按「外部托管」假设，清单里只有业务服务的 Deployment/Service。

## 代码结构

| 目录 | 作用 |
|---|---|
| `services/api-gateway` | 主后端：认证、用户、租户、知识库、文档、对话、检索、工作流、模型、成本、审计、内部服务接口 |
| `services/{auth,document,rag,llm,workflow,notification}-service` | 可独立拆分的微服务；auth/notification/llm/document/workflow 已可在本地 SQLite 下启动并通过冒烟测试 |
| `services/*/app/core/context.py` | 微服务请求上下文：从 `X-Tenant-Id` / `X-User-Id` 解析租户与操作人（缺省为演示租户），供所有查询/写入做租户隔离 |
| `services/*/app/core/service_auth.py` | 服务间签名校验（HMAC-SHA256 + 300 秒时差窗口）；配置 `SERVICE_API_KEY` 后未签名请求一律 401 |
| `apps/web` | 用户工作台（知识库、流式对话、工作流编辑器） |
| `apps/admin` | 管理后台（本仓库最近补齐：登录门禁 + 真实数据） |
| `packages/*` | 共享类型、UI 组件、配置 |
| `infra/*` | Dockerfile、K8s/Helm、GitHub Actions |
| `tests/` | 跨服务冒烟测试（`test_gateway_smoke.py`、`test_microservices_smoke.py`） |

> 进度、待办与已知风险统一记录在 `docs/PROGRESS.md`；工作约定见根目录 `AGENTS.md`。

## 一次 RAG 对话的数据流

1. Web 调用 `POST /api/v1/conversations/chat/completions`，带 `knowledge_base_id`。
2. 网关校验 JWT + 租户，把问题向量化（`/models` 中的 embedding 模型）。
3. `retrieval` 在知识库内做向量/混合检索（pgvector 或 SQLite 余弦），返回 top-k 片段。
4. 拼上下文 + 提示词，调用 `llm-service`（或直接供应商 SDK），流式回传。
5. 落库：`messages`、`usage_records`（token 与成本）、`audit_logs`；预算超限则拒绝后续调用。

## 关键设计决策

- **认证与授权分离**：JWT 只回答"你是谁"，`require_roles` 回答"能做什么"，租户过滤写在 SQL 条件里回答"能看哪些行"。
- **启动即迁移**：7 个服务（网关 + 6 个微服务）启动时统一 `alembic upgrade head`（`DB_AUTO_MIGRATE`）；
  旧库（有表、无 `alembic_version`）先 `stamp head` 并打警告——不校验列差异，只适合本地/演示库。
- **默认 SQLite**：开箱即用，不依赖 Docker；`DATABASE_URL` 换成 `postgresql+asyncpg://...` 即切回 PostgreSQL，模型层已做类型兼容（`app/db/types.py`）。
- **统一响应包络**：`{success, data, error, meta}`，错误体 `{code, message, details}`，前端只需一套解包逻辑。
- **成本护栏**：每次模型调用写 `usage_records`，`/costs/budget` 提供租户月度预算与使用率。
- **审计只读**：`audit_logs` 只有查询/导出接口，没有更新与删除。

## 当前完成度

| 能力 | 状态 |
|---|---|
| 认证（登录/刷新/改密/登出）、RBAC、多租户 | ✅ 可运行 |
| 知识库 / 文档上传解析 / 分块 / 检索 | ✅ 接口完整 |
| 对话（含流式、引用）与用量计费 | ✅ 接口完整，取决于是否配置模型 Key |
| 工作流 CRUD / 发布 / 执行 | ✅ 接口完整 |
| 模型配置（列表 + 启用/停用） | ✅ 网关 PATCH 接口 + 管理后台 |
| 管理后台（用户/租户/模型/审计/成本） | ✅ 已接真实 API |
| 审计事件写入 | ✅ 登录成功/失败、登出、用户增删改、模型启停、租户创建/修改 |
| 微服务拆分运行（auth/document/rag/llm…） | ✅ 5 个服务可用 `start-microservices.cmd` 在 SQLite 下独立启动；rag-service 已在真实 PostgreSQL + pgvector 上跑通知识库/文档 CRUD |
| 微服务身份信任边界 | ✅ 第 6 轮：HMAC 服务间签名（`SERVICE_API_KEY`），未签名 / 伪造 / 过期 → 401；`test_microservices_smoke.py` 13 项通过（rag 未启动时跳过 3 项） |
| 文档 → RAG 自动串联 | ✅ 第 8 轮：document-service 解析完成 → 带签名调用 rag `POST /documents/ingest`（登记 + 分块 + 嵌入 + BM25 刷新），响应 `rag_ingested` 标记结果；rag 挂掉不影响上传（best-effort） |
| 两条上传链路行为一致 | ✅ 第 9 轮：`/documents/{id}/process` 与预签名 `/upload/complete` 共用 `_parse_and_ingest()`；complete 默认自动解析+入库（`AUTO_PROCESS_ON_UPLOAD`），响应 `processed` / `document_status` / `rag_ingested`，解析失败不回滚上传 |
| local 存储的预签名 URL | ✅ 第 9 轮：document-service 签名豁免 `/api/v1/storage/*`（能力型地址，与 MinIO presigned 同语义）；修复第 6 轮引入的本地预签名 PUT/GET 401 回归 |
| MinIO/S3 后端 | ✅ 第 17 轮：用 `moto` 内存 S3 端点跑通桶创建、multipart put、预签名 PUT/GET、下载与解析（local 与 minio 两种后端冒烟结果一致） |
| 网关 → 工作流转发 | ✅ 第 13 轮：`/workflows` 全 CRUD + validate/publish/execute/executions 可转发到 workflow-service，图结构双向转换（`GATEWAY_PROXY_WORKFLOWS`）；`unpublish` 明确 501 |
| 网关代理层权限 | ✅ 第 14 轮：转发前按方法/路径映射回网关 RBAC（`document:*`、`workflow:*`），VIEWER 写操作 403 |
| 知识库统计与转发对齐 | ✅ 第 15 轮：转发模式下 `/knowledge-bases` 的计数与最近文档改由 document-service 内部接口 `POST /api/v1/internal/kb-stats` 提供（失败回退本地计数）；软删除后同内容重传会复活原记录 |
| 网关 → 微服务转发 | ✅ 第 10/11 轮（试点）：`/documents` `/upload` `/download` 可经网关转发到 document-service，网关负责 JWT 鉴权、HMAC 签名、租户/用户注入，并把响应包回 `{success, data}` 信封 + 网关字段名（`proxy_adapters.py`）；上传/下载为流式转发（不整块缓冲）；`GATEWAY_PROXY_DOCUMENTS` 默认关闭（两套 SQLite 数据不互通） |
| RAG 依赖失败语义 | ✅ 第 8 轮：embedding 不可用 → `/embeddings`、`/documents/*` **503 + 可读文案**；`/retrieval/search` 降级 BM25-only 并返回 `degraded` / `degraded_reason`，无命中才 503 |
| 生产构建 | ✅ `next build` 通过（web 8 路由 / admin 8 路由） |
| 文档与冒烟测试 | ✅ `docs/` + `tests/test_gateway_smoke.py` |
