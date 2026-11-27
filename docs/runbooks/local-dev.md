# 本地开发 Runbook

## 端口约定

| 端口 | 服务 |
|---|---|
| 8000 | API 网关（FastAPI） |
| 3001 | 管理后台（apps/admin） |
| 3002 | 用户工作台（apps/web） |
| 6379 | Redis（可选） |
| 11434 | Ollama（可选，本地模型） |

## 启动

```powershell
# 首次：在仓库根装依赖（单一 pnpm workspace，只有一份 pnpm-lock.yaml）
pnpm install

# 一键：网关 + 工作台
start-dev.cmd

# 手动三件套
cd services/api-gateway
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

cd apps/web   && pnpm dev      # :3002
cd apps/admin && pnpm dev      # :3001
```

依赖只在根目录装一次（`apps/*`、`packages/*` 由 `pnpm-workspace.yaml` 管理），不要在子目录里
`pnpm install`——那会生成第二份锁文件，CI 的 `--frozen-lockfile` 就对不上了。根目录常用命令：

```bash
pnpm lint        # turbo: next lint（两个 app）+ eslint（三个 packages）
pnpm typecheck   # turbo: 两个 app + 三个 packages 的 tsc --noEmit
pnpm test        # turbo: vitest（web 45 + admin 34）
pnpm test:coverage   # 同上并产出 apps/*/coverage/lcov.info
pnpm build       # turbo: packages 的 tsc + 两个 next build
```

演示账号（SQLite 演示数据）：`admin@example.com / admin123`。

健康检查：

```bash
curl http://127.0.0.1:8000/health
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/openapi.json
```

## 微服务（可选）

| 服务 | 本地端口 | 本地数据库 | 额外依赖 |
|---|---|---|---|
| auth-service | 8007 | SQLite `auth.db` | — |
| notification-service | 8006 | SQLite `notification.db` | SMTP（可选，未配置只入库不外发） |
| llm-service | 8003 | SQLite `llm_dev.db` | 各供应商 API Key（仅调用模型时需要） |
| document-service | 8004 | SQLite `document_dev.db` + `./data/storage` | 默认 `STORAGE_PROVIDER=local`；要接 MinIO 就改环境变量 |
| workflow-service | 8005 | SQLite `workflow_dev.db` | — |
| rag-service | 8001 | PostgreSQL + pgvector | Redis（向量检索走 `cosine_distance`，SQLite 不支持） |

前五个服务可以直接启动，**不需要 Docker**：

```powershell
# 一键：各服务一个窗口，自动等待 /health
start-microservices.cmd     # 或 powershell -File start-microservices.ps1
```

手动启动其中一个（必须在该服务目录下启动，SQLite 是相对路径）：

```bash
cd services/llm-service
DATABASE_URL="sqlite+aiosqlite:///./llm_dev.db" DEBUG=false PYTHONUTF8=1 \
  ../api-gateway/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8003
```

注意 auth-service 的默认端口是 8000，和网关冲突，用 `PORT=8007` 覆盖。

rag-service 需要 PostgreSQL + pgvector（已实测可用），先起基础设施再启动：

```bash
docker compose up -d postgres redis   # init.sql 已建 vector 扩展
cd services/rag-service
DATABASE_URL="postgresql+asyncpg://enterprise_ai:enterprise_ai_dev@localhost:5432/enterprise_ai" \
  REDIS_URL="redis://localhost:6379/2" DEBUG=false BM25_INDEX_PATH="./data/bm25_index" \
  EMBEDDING_API_BASE="http://127.0.0.1:11434/v1" EMBEDDING_API_KEY="ollama" \
  EMBEDDING_MODEL="embeddinggemma:300m" EMBEDDING_DIM=768 \
  PYTHONUTF8=1 ../api-gateway/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

- 首次启动会自动 `alembic upgrade head`（第 18 轮起）建 `knowledge_bases / documents / document_chunks` 三张表并启 `vector` 扩展。
- **embedding**：本地没有 OpenAI Key 时指向本机 Ollama（`embeddinggemma:300m` 是 768 维，所以 `EMBEDDING_DIM=768`）。
  向量列维度跟 `EMBEDDING_DIM` 走：**换维度需要重建 `document_chunks` 表**（开发库可直接 drop）。
- 用 OpenAI 时把 `EMBEDDING_DIM` 改回 1536 并重新建表。
- 入库正文：登记文档时把已解析正文放进 `metadata.text`，`/documents/{id}/process` 会直接用它分块/嵌入。
- **一键入库**：`POST /api/v1/documents/ingest`（`knowledge_base_id + title + text`）一次完成登记 + 分块 + 嵌入 + BM25 刷新，
  同一 `file_hash` 复用文档。document-service 的 `/documents/{id}/process` 解析成功后会自动调它
  （`RAG_SERVICE_URL`，`AUTO_INGEST_TO_RAG=false` 可关），响应里看 `rag_ingested`。
- **预签名上传同样自动解析**：`/upload/complete` 成功后默认立即解析（`AUTO_PROCESS_ON_UPLOAD=false` 可关），
  解析成功再自动入库；响应里的 `processed` / `document_status` / `rag_ingested` 直接告诉你走到哪一步，
  解析失败不会回滚上传（文档保留、状态 FAILED、带 `process_error`）。
- **BM25**：索引按知识库落盘在 `BM25_INDEX_PATH`，文件名带 `_v3.pkl`（分词/打分器版本）；
  新环境冷启动会自动从 DB 重建。embedding 不可用时检索会降级为 BM25 并在响应里标 `degraded`。
- **Docker Hub 在本机不可直连**：`postgres` / `redis` 用的是已缓存镜像；
  `minio/minio` 拉不到（Docker Hub 超时、quay 未授权、镜像源无 tag，官方 Windows 二进制也是 410），
  所以 MinIO 模式仍未验证，本地统一用 `STORAGE_PROVIDER=local`（详见 `docs/PROGRESS.md` 第 12 轮）。

6 个服务共用网关的 venv（本地未单独建 venv）即可完成导入检查：

```bash
cd services/rag-service && ../api-gateway/.venv/Scripts/python.exe -c "import app.main; print('ok')"
```

本地日常开发不需要它们：网关单体已经包含同样的业务接口，这也是默认运行方式。

### 网关转发试点（第 10–13 轮）

默认关闭。要把 `/documents`、`/upload`、`/download` 交给 document-service，需要**两侧同一个密钥**：

```bash
# 1) 先起 document-service（带 SERVICE_API_KEY，见上）
cd services/api-gateway
SERVICE_API_KEY="dev-internal-key" GATEWAY_PROXY_DOCUMENTS=true \
  PYTHONUTF8=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 网关会先验证 JWT，再把身份换成 `X-Tenant-Id` / `X-User-Id` + HMAC 签名转发；`Authorization` 不透传。
- 没配 `SERVICE_API_KEY` 时转发返回 **503**（不会静默发无签名请求）；document-service 没起是 **502**。
- 响应已包回网关的 `{success, data}` 信封，字段名也用 `file_name` / `mime_type` / `type`
  （转换在 `app/api/v1/proxy_adapters.py`）：列表分页、创建、上传（含自动解析）、详情、删除、重解析都已完成；
  但 `/documents/{id}/chunks` 在转发模式下返回 **501**（微服务没有分块接口），
  列表的 `search` / `type` 过滤会被忽略。
- 上传/下载与未适配路径都是**流式转发**（请求体 `request.stream()`，响应 `StreamingResponse`），
  大文件不会在网关里再缓冲一份；只有 JSON 与错误体会读完再包信封。
- 下载路径映射：网关 `GET /api/v1/documents/{id}/download` → 微服务 `/api/v1/download/{id}`。
- 知识库统计：开关打开后，`/knowledge-bases` 的 `document_count` 等字段由网关签名调用
  document-service 的 `POST /api/v1/internal/kb-stats` 获取（失败则回退网关本地计数并打 warning）。
- 上传去重：`documents` 的 `(tenant_id, file_hash)` 唯一约束包含软删除行，所以「删除后再传同一份内容」
  会复活原记录（ID 不变），而不是新建或 500。

工作流同理，另一个开关（需 workflow-service 8005 也在跑）：

```bash
SERVICE_API_KEY="dev-internal-key" GATEWAY_PROXY_WORKFLOWS=true \
  WORKFLOW_SERVICE_URL="http://127.0.0.1:8005" \
  PYTHONUTF8=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 覆盖列表/创建/详情/PATCH/删除/`validate`/`publish`/`execute`/`executions`；
  网关与微服务的工作流图结构不同，代理层会做**双向转换**（节点 `type` 大小写、`name` 存 `config.name`、
  边 `source_node_id/target_node_id` ↔ `source/target`）。
- `/workflows/{id}/unpublish` 在微服务没有对应接口 → **501**（改用 PATCH 把 status 设为 archived，
  但微服务不允许改已发布工作流，实际需要先在微服务侧补接口）。
- 两个开关都**已按方法/路径映射补回网关 RBAC**（第 14 轮）：VIEWER 读 200、写 403；
  资源归属仍由微服务按租户校验。
- 验证：`tests/test_microservices_smoke.py` 的 `test_gateway_forwards_documents_with_jwt_identity`
  （网关未开转发时自动 skip）。

### 通知转发（第 26 轮）

通知是第三个接入转发的资源，开关独立：

```bash
# 1) 先起 notification-service（8006，会自己跑到 002_gateway_contract）
cd services/notification-service
SERVICE_API_KEY="dev-internal-key" DATABASE_URL="sqlite+aiosqlite:///./notification.db" \
  PYTHONUTF8=1 ../api-gateway/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8006

# 2) 网关打开通知转发
cd services/api-gateway
SERVICE_API_KEY="dev-internal-key" GATEWAY_PROXY_NOTIFICATIONS=true \
  PYTHONUTF8=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 两侧契约已对齐（`002_gateway_contract`）：UUID 主键 + `user_id/title/data/read`，
  转发层不再伪造 ID；`GET /notifications` 的分页用微服务的 `X-Total-Count` 拼回网关信封。
- 服务按 `X-User-Id` 过滤，只返回当前用户的通知；`X-Tenant-Id` / `X-User-Id` 不是 UUID 直接 **400**。
- 权限：列表/已读/删除登录即可，创建要求 ADMIN / SUPER_ADMIN（与网关原路由一致）。
- 降级：`GET /notifications/{id}`（网关没有详情路由）→ **501**；邮件 / Webhook 真正发送仍是 TODO。
- 验证：`pytest tests/test_microservices_smoke.py -k "notification or ready"`
  （`test_gateway_forwards_notifications` 在网关未开开关时自动 skip）。

### 通知中心页面（第 27 轮）

前端不用管通知是谁提供的（网关自带实现，或开关打开后的 notification-service）：

- 入口：导航栏铃铛（登录后才显示，带未读数徽标 + 最近 6 条 + 「全部已读」）；完整页 `/notifications`
  （`全部 / 未读` 筛选、逐条标记已读、删除、全部已读、刷新）。
- 请求层：`api.getNotifications({ unread_only, limit })` / `getUnreadNotificationCount()` /
  `markNotificationRead(id)` / `markAllNotificationsRead()` / `deleteNotification(id)`，
  分页参数仍是 `limit` → `page_size`，响应经拦截器解包成数组。
- 造数据（只有 ADMIN 能创建，不传 `user_id` 时默认发给自己）：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login   -H 'Content-Type: application/json'   -d '{"email":"admin@example.com","password":"admin123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
curl -s -X POST http://127.0.0.1:8000/api/v1/notifications   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"title":"测试通知","content":"来自 curl","type":"INFO","channel":"IN_APP"}'
```

- 注意：`NEXT_PUBLIC_API_URL` 的兜底值已从 **8200 改成 8000**（`lib/api.ts` + `next.config.js`）。
  没有 `apps/web/.env.local` 时（CI / 新克隆）直接连网关，不再打到空端口。
- 验证：`cd apps/web && ./node_modules/.bin/playwright test tests/e2e/notifications.spec.ts`（需要网关 8000）。

### 通知由哪些业务事件产生（第 28 轮）

`app/services/notify.py` 是唯一出口：写失败只记日志，不影响主流程；`GATEWAY_PROXY_NOTIFICATIONS`
打开时自动改投 notification-service（带 `internal_headers()` 签名），所以前端在两种模式下都能看到。

| 事件 | 触发点 | 通知 |
|---|---|---|
| 上传后解析完成（默认管线） | `documents.upload_document` | SUCCESS《文件名》解析完成，正文带分块数 / tokens |
| 解析失败（空文件等） | 同上 / `reprocess` | WARNING《文件名》解析失败，正文是错误原因 |
| 重新解析 | `documents.reprocess_document` | SUCCESS / WARNING，标题带「重新」 |
| 转发模式「上传即解析」 | `proxy._upload_document` | 解析在 document-service 侧完成，通知由网关补发 |
| 工作流执行结束 | `proxy_workflows._execute` | completed → SUCCESS，failed → ERROR，cancelled → WARNING |

所有通知的 `data` 都带 `event` + 资源 id（`document_id` / `workflow_id` / `execution_id`）。

- 默认模式验证：`pytest tests/test_gateway_smoke.py -q`（含 `test_upload_creates_notification` 与
  `test_failed_parse_creates_warning_notification`，会自己清理产生的文档与通知）。
- 转发模式验证：起 notification-service 8006 + 网关 `GATEWAY_PROXY_NOTIFICATIONS=true`，
  再跑上面两条用例 —— 通知写进微服务、经网关列表读回。
- 注意：默认模式的 `POST /workflows/{id}/execute` 只建 PENDING 记录（执行器 TODO），
  所以「工作流执行结束」通知只在 `GATEWAY_PROXY_WORKFLOWS=true` 时出现。

### 工作流执行（第 29 轮，默认模式）

默认单体模式不再只插一条 PENDING 记录：`POST /api/v1/workflows/{id}/execute` 会真的按 DAG 跑一遍。

| 节点类型 | 行为 |
|---|---|
| START | 把请求里的 `input_data` 带进上下文 |
| END | 输出当前全部变量（`output.output`） |
| HTTP | 真发请求（15s 超时、跟随重定向），响应 JSON 并进变量，后续节点可用 `{{field}}` |
| DELAY | 等待 `config.duration_ms`（上限 10s） |
| LLM | `prompt_template`（`{{变量}}` 渲染）→ Ollama `/api/chat`；输出 content / model / token 数，写一条 `cost_records`（`workflow_llm`） |
| RAG | `knowledge_base_id` + `query_template` + `top_k` → 本地关键词检索；输出 count / chunks，`{{rag_context}}` 供后续 LLM 节点使用 |
| CONDITION / TRANSFORM / PARALLEL / MERGE | **预检直接失败**，提示改用 `GATEWAY_PROXY_WORKFLOWS=true` 走 workflow-service |

- 执行记录：`RUNNING → COMPLETED / FAILED`，带 `output` / `error` / `completed_at` / `node_executions`
  （节点级 status、output、error、started_at、duration_ms；时间是 ISO 字符串）。
- 结束会写站内通知（SUCCESS / ERROR），与第 28 轮同一个出口。
- 前端执行按钮按真实状态提示：`COMPLETED` 才 success，否则把 `error` 弹出来。

```bash
# 建一个 START → END 的工作流、发布、执行（admin token 见「通知中心页面」一节）
curl -s -X POST http://127.0.0.1:8000/api/v1/workflows   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"name":"demo","definition":{"nodes":[{"id":"start","type":"START","name":"开始","position":{"x":0,"y":0},"config":{}},{"id":"end","type":"END","name":"结束","position":{"x":200,"y":0},"config":{}}],"edges":[{"id":"e1","source_node_id":"start","source_port_id":"out","target_node_id":"end","target_port_id":"in"}]}}'
# 发布（拿到 id 后）
curl -s -X POST http://127.0.0.1:8000/api/v1/workflows/<id>/publish -H "Authorization: Bearer $TOKEN"
# 执行
curl -s -X POST http://127.0.0.1:8000/api/v1/workflows/<id>/execute   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"input_data":{"message":"hi"}}'
```

- 注意：HTTP 节点当前**没有 SSRF 防护**（能访问内网地址），生产前必须加白名单；执行是同步的。
- LLM 节点依赖本机 Ollama（默认 `http://127.0.0.1:11434`，模型 `qwen2.5-coder:1.5b`）：
  没起时节点会 FAILED，错误里直接写「连不上 …（检查 OLLAMA_BASE_URL / OLLAMA_CHAT_MODEL）」。
  `OPENAI_*` 还没实现，配 Key 也不会走。
- 每次 LLM 节点调用都会写一条成本记录（`operation_type=workflow_llm`，本地模型金额 0、token 真实）；
  `/costs/summary` 的 `by_operation` 里能看到。

### 租户 / 用户请求头（微服务）

微服务自身不做鉴权，身份来自调用方注入的请求头：

| 请求头 | 含义 | 缺省 |
|---|---|---|
| `X-Tenant-Id` | 租户 UUID | 演示租户 `00000000-0000-0000-0000-000000000001` |
| `X-User-Id` | 操作人 UUID | 演示用户（同上） |

代码入口是各服务的 `app/core/context.py`（`current_tenant_id()` / `current_user_id()`）。
头里不是合法 UUID 会直接返回 **400**，不会静默落到演示租户。示例：

```bash
curl -s -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" \
  http://127.0.0.1:8004/api/v1/documents
```

> 这层头是**内部信任边界**：第 6 轮起由 HMAC 签名保护，直连端口不再能冒充租户。

### 服务间签名（第 6 轮新增）

配置了 `SERVICE_API_KEY` 后，所有 `/api/v1/*` 必须带签名，否则 **401**（`/health`、`/ready`、`/metrics`、
`/docs`、`/openapi.json` 豁免）：

> document-service 额外豁免 `/api/v1/storage/*`：local 存储模式的 presigned PUT/GET 就指向这里，
> 调用方是浏览器/客户端，不可能带服务间签名（与 MinIO 预签名 URL 的「持链接即可读写」语义一致）。
> 设了 `SERVICE_API_KEY` 后手工调 `/upload/complete`、`/download/{id}` 同样要签名。

| 请求头 | 含义 |
|---|---|
| `X-Service-Timestamp` | unix 秒，允许与服务器相差 ±300 秒 |
| `X-Service-Signature` | `hex(hmac_sha256(SERVICE_API_KEY, "METHOD
PATH
tenant
user
ts"))` |

- `start-microservices.ps1` 已给 5 个服务注入 `SERVICE_API_KEY=dev-internal-key`；根 `.env` 里有同名变量供测试读取。
- **密钥为空 = 本地开发模式，不校验**（此时任何人都能直连端口）。生产必须显式配置，且网关与所有服务用同一个值。
- 网关转发用 `services/api-gateway/app/core/internal_auth.py#internal_headers()` 生成这两个头。
- 手工 curl 调试若不想签名，把 `SERVICE_API_KEY` 留空启动即可（dev 模式）。

示例（签名生效后，不带签名会 401）：

```bash
curl -s -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111"   http://127.0.0.1:8004/api/v1/documents
# {"detail":"缺少服务间签名（需要 X-Service-Timestamp 与 X-Service-Signature）"}
```

两个探针：`/health` 只证明进程活着；`/ready` 会真 ping 一次数据库，连不上返回 503。

## 数据与配置

- 网关默认 `DATABASE_URL=sqlite+aiosqlite:///./data/enterprise_ai.db`，**相对路径**：必须在 `services/api-gateway` 目录下启动，否则会新建空库并重新种子演示数据。
- 想重置演示数据：停掉网关，删除 `services/api-gateway/data/enterprise_ai.db*`，再启动。
- 根目录 `.env` 提供模型 Key 与开关（`OPENAI_API_KEY` / `OLLAMA_BASE_URL` …）。没有 Key 时对话接口会报错，其余管理功能不受影响。
- 管理后台/工作台通过 Next rewrite 走同源 `/api/*` → `http://localhost:8000/api/*`，因此不需要配 CORS；如需直连后端，在对应 app 的 `.env.local` 设 `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1`。

## 测试

```bash
# 网关冒烟（20 项：健康、认证、用户、租户、模型、审计、成本、权限、校验 + 上传解析通知 2 项
#          + 工作流执行器 3 项：START→END / 条件分支明确不支持 / HTTP 真请求
#          + AI 节点 2 项：LLM 真调用 + 成本记录、RAG 真检索（LLM 用例在没起 Ollama 时自动 skip））
python tests/test_gateway_smoke.py

# 微服务冒烟（20 项：6 个服务真实读写 + 租户隔离 + /ready + 签名三连 + RAG 检索链路 + 上传即入库/503 映射/自动串联 + 预签名自动解析入库与文档上传下载 + 网关转发（文档/工作流）+ 转发 RBAC；未启动的服务自动跳过）
python tests/test_microservices_smoke.py

# 前端单元测试（在仓库根跑，一条命令带上 admin 与 web）
pnpm test               # web 45 + admin 34（管理后台不需要后端）

# 只跑某一个 app
pnpm --filter @enterprise-ai/web   run test
pnpm --filter @enterprise-ai/admin run test

# 类型检查 / 构建（根目录）
pnpm typecheck
pnpm build

# ============================================
# 验证 MinIO 存储分支（无需 Docker / 真实 MinIO）
# ============================================
# 拿不到 minio 镜像时（registry 超时、dl.min.io 410），用 moto 的内存 S3 端点跑同一套冒烟：
.\.venv\Scripts\python.exe -m pip install "moto[server]"   # 仅本地验证，未加入 requirements
.\.venv\Scripts\python.exe -m moto.server -p 9000            # 另开一个终端，保持运行

cd services/document-service
DATABASE_URL="sqlite+aiosqlite:///./document_minio_test.db" STORAGE_PROVIDER=minio \
MINIO_ENDPOINT="127.0.0.1:9000" MINIO_ACCESS_KEY="minioadmin" MINIO_SECRET_KEY="minioadmin123" \
MINIO_BUCKET="documents" MINIO_USE_SSL=false MINIO_REGION="us-east-1" \
PUBLIC_BASE_URL="http://127.0.0.1:8004" SERVICE_API_KEY="dev-internal-key" \
AUTO_INGEST_TO_RAG=true PYTHONUTF8=1 ../api-gateway/.venv/Scripts/python.exe \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8004

# 然后用同一套冒烟（21 项）验证；结束后可删掉 document_minio_test.db。
# 注意：moto 是 S3 协议内存实现，不覆盖桶策略、分片上传、分布式等 MinIO 特有行为。

# E2E（chromium；自动起对应 dev server，依赖接口的用例需要网关 8000 在跑，否则自动 skip）
cd apps/web   && ./node_modules/.bin/playwright test   # 9 项：登录、工作流编辑器、通知中心（自动起 3002）
cd apps/admin && ./node_modules/.bin/playwright test   # 8 项：登录/退出、五页导航、用户搜索、审计明细（自动起 3001）
```

> CI 里的 `smoke-tests` job 就是把「起网关 → 跑 `tests/test_gateway_smoke.py`」自动化：
> 用 SQLite、`DB_AUTO_MIGRATE=true`，轮询 `/health` 最多 120s。本地按同样顺序手跑即可复现。
>
> `e2e-tests` job 是同一套路：起网关后**先 curl 演示账号登录（必须 200）**，再跑 admin 8 项 + web 9 项；
> 少了登录门禁，后端没起来时 E2E 会全 skip 而 job 仍绿。

## 发版（changesets）

- 改了 `apps/*` / `packages/*` 的代码后加一条 changeset：`pnpm changeset`（交互式）或手写
  `.changeset/<名字>.md`（格式见 `.changeset/README.md`）。
- 合到 `main` 后 `release` job 会开一个「版本 PR」（`chore: version packages`），内容是版本号 + CHANGELOG；
  **本项目不发布 npm**：`apps/*` 都是 private，`config.json` 里 `privatePackages.version=true`、`tag=false`，
  所以不需要 `NPM_TOKEN`。
- 本地看有哪些待发布：`pnpm changeset status` —— **需要 git 仓库且存在 `main` 分支**。
  当前项目目录不是 git 仓库，直接跑会报 `Failed to find where HEAD diverged from "main"`（不是配置错）。
- 没有 changeset 时 `status` 退出码是 1，CI 里已用 `|| echo` 兜住，不会卡住发版。

## 常见问题

**1. 端口被占（Windows 上 `SO_REUSEADDR` 会让多个进程同时监听）**

```bash
netstat -ano | findstr ":8000" | findstr LISTENING
taskkill /F /PID <pid>
```

启动前务必确认只有一个网关实例，否则请求会随机命中旧进程。

**2. `/api/v1/openapi.json` 打开是乱码或解析失败**

先确认不是用 GBK 终端去 `python -c json.load(sys.stdin)` 读的——Windows 控制台默认不是 UTF-8，请用 `PYTHONUTF8=1` 或 `Invoke-RestMethod`。

**3. 管理后台登录后 401 / 跳回登录页**

令牌默认 15 分钟过期。清理浏览器 `localStorage` 的 `access_token`、`refresh_token` 后重新登录。

**4. Next dev 卡在 "Failed to download Inter from Google Fonts"**

离线环境正常现象（已改为系统字体，不会阻塞）；若仍出现，检查是否有旧的 `.next` 缓存，删除后重启。

**5. 数据库表结构变更后启动报错**

本地 SQLite 演示库想重来：停服务、删库、重启（会自动重建到最新迁移）。

### Python 静态检查（ruff）

CI 的 `python-lint` job 跑的就是同一条命令，本地先过一遍再提交：

```bash
./services/api-gateway/.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./services/api-gateway/.venv/Scripts/ruff.exe check services tests
```

- 规则在仓库根 `ruff.toml`（只开 `E4/E7/E9/F`），**不要用 `ruff check --select ALL`**：
  本机若有用户级 ruff 配置（默认把全部规则打开），会报出几百个风格问题，与 CI 结果不一致。
- 显式忽略 `E712`（SQLAlchemy 的 `== True` 必须这么写）与 `E402`（FastAPI 常用的函数内导入）。
- 自动修：`ruff check services tests --fix`（只处理安全修复，主要是未使用 import）。

### Kubernetes 清单自检（不需要集群）

清单的权威版本是 `infra/k8s/base` + `overlays/{dev,staging,prod}`（ArgoCD 的 `applications.yaml` 指的就是 overlay），
`infra/k8s/helm` 那套 chart 目前没人用。

```bash
kubectl kustomize infra/k8s/overlays/dev      # 只渲染，不连集群；应 exit 0
kubectl kustomize infra/k8s/overlays/prod
```

两个踩过的坑（改清单时别再踩）：

- `configMapGenerator` / `secretGenerator` 用 `behavior: merge` 时**必须写 `namespace: enterprise-ai`**，
  否则 kustomize 在 accumulation 阶段匹配不到 base 里的同名对象，报
  `does not exist; cannot merge or replace`。
- overlay 里**不要**再写 `namespace:`：namespace transformer 会把 base 的 `Namespace` 对象一起改名
  （`monitoring` 也被改成 `enterprise-ai`），直接 `namespace transformation produces ID conflict`。

端口以服务真实监听为准：网关 8000、rag 8001、llm 8003、document 8004、workflow 8005、
notification 8006、auth 8007（`PORT=8007` 覆盖默认 8000）、web 3000、admin **3000**（`next start` 默认，compose 里映射成宿主机 3001）。

### 数据库迁移（Alembic，7 个服务）

**7 个服务启动时都会自动** `alembic upgrade head`（`DB_AUTO_MIGRATE=false` 才退回 `create_all`）：
网关 / rag / auth / notification / document / llm / workflow 的 `app/db/session.py` 是同一套逻辑
（探表用 async 引擎 → 有版本表就 upgrade；旧库先 `stamp head`）。
旧库（有表、没有 `alembic_version`）启动时会先 `stamp head` 并打印警告：**stamp 不校验列差异**，
只适合本地/演示库；有手工改过表的库要先自己跑一次 `alembic check`。

手动命令（在对应服务目录，用同一个 venv）：

```bash
../api-gateway/.venv/Scripts/python.exe -m alembic upgrade head      # 升到最新
../api-gateway/.venv/Scripts/python.exe -m alembic check            # 模型 vs 库 是否漂移
../api-gateway/.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add xxx"
```

注意：

- 7 个服务都已有 `alembic/script.py.mako`，`revision --autogenerate` 直接用，不要再手工拷迁移文件。
- `alembic.ini` 按系统编码读取（中文 Windows 是 GBK），**只能写 ASCII**，否则 `UnicodeDecodeError`。
- 迁移里不要用 `op.create_enum`（Alembic 没这个 API）；pg 枚举用 `postgresql.ENUM(..., create_type=False)` + 显式 `.create(checkfirst=True)`。
- rag 是 PostgreSQL + pgvector：baseline 自带 `CREATE EXTENSION IF NOT EXISTS vector`，空库能直接升。
