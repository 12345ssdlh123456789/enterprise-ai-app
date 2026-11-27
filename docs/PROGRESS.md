# 项目进度与交接（PROGRESS）

> 最后更新：2026-11-26
> 维护规则见根目录 [`AGENTS.md`](../AGENTS.md)：**每完成一轮改动都要回来更新本文档**。

本文档回答三个问题：**现在能跑什么**、**已经做完什么**、**下一步该做什么**。
架构细节看 `docs/architecture/overview.md`，**服务拆分现状/资源归属** 看 `docs/architecture/service-split.md`，
本地启动看 `docs/runbooks/local-dev.md`，接口看 `docs/api/README.md`。

---

## 1. 一句话现状

网关 + 管理后台 + 用户工作台三端可用（SQLite 演示数据、真实登录、真实审计落库），
五个微服务可在本地 SQLite 下独立启动并通过冒烟测试；只有 rag-service 仍依赖 PostgreSQL + pgvector。
文档、工作流、通知三块都可以按开关转给微服务（`GATEWAY_PROXY_DOCUMENTS/WORKFLOWS/NOTIFICATIONS`）。
文档解析完成/失败、工作流执行结束会自动写站内通知（两种通知后端都写对），通知中心不再是空壳。
默认模式的工作流有了真执行器（START/END/HTTP/DELAY/LLM/RAG），点「执行」会真的跑完并给出结果；
LLM 节点走 Ollama、RAG 节点走本地关键词检索，调用会记 token 成本。
管理后台 34 项单测 + 8 项 Playwright E2E、工作台 45 项单测 + 9 项 E2E 全绿，两者都已进 CI（`e2e-tests` job）。
7 个服务启动时统一执行 Alembic 迁移（`DB_AUTO_MIGRATE`，默认开），旧库（有表无版本表）会自动 `stamp head`；
`infra/k8s` 的 base + 三个 overlay 已按真实服务名/端口对齐并能用 `kubectl kustomize` 渲染。

---

## 2. 现在能跑什么

| 组件 | 端口 | 数据存储 | 启动方式 | 状态 |
|---|---|---|---|---|
| API 网关（单体后端） | 8000 | SQLite `services/api-gateway/data/enterprise_ai.db` | `start-dev.cmd` / uvicorn | ✅ 可用，20 项冒烟通过；文档解析/工作流执行会自动写通知 |
| 管理后台 apps/admin | 3001 | — | `start-dev.cmd` | ✅ 五个页面 + 总览，`tsc --noEmit` 通过，34 项单测 + 8 项 Playwright E2E 通过 |
| 用户工作台 apps/web | 3002 | — | `start-dev.cmd` | ✅ 首页 / 知识库 / 工作流 / 通知中心，`next build` 通过，45 项单测 + 9 项 E2E |
| auth-service | 8007（默认 8000 冲突，用 `PORT=` 覆盖） | SQLite `auth.db` | `start-microservices.cmd` | ✅ `/ready` 探活数据库 |
| notification-service | 8006 | SQLite `notification.db` | 同上 | ✅ 创建/列表/已读/删除；可经网关转发（`GATEWAY_PROXY_NOTIFICATIONS`），业务事件也会自动写入 |
| llm-service | 8003 | SQLite `llm_dev.db` | 同上 | ✅ Provider/Model/成本汇总 |
| document-service | 8004 | SQLite `document_dev.db` + 本地目录 `./data/storage` | 同上（`STORAGE_PROVIDER=local`） | ✅ 上传 / 下载 / 解析全链路已验 |
| workflow-service | 8005 | SQLite `workflow_dev.db` | 同上 | ✅ 创建/校验/执行记录 |
| rag-service | 8001 | PostgreSQL + pgvector（Docker） | `docker compose up -d postgres redis` + uvicorn | ✅ 知识库/文档 CRUD + 分块/嵌入/向量检索全链路（Ollama `embeddinggemma:300m`） |

演示账号：`admin@example.com / admin123`，租户 `Demo Tenant / demo`。

---

## 3. 已完成（最新在上）

### 2026-11-26 · 第 30 轮：工作流能真正跑 AI 节点（LLM / RAG）

**背景**：第 29 轮的执行器只会 START / END / HTTP / DELAY —— 一个「企业 AI 应用」的工作流
却调不了模型、查不了知识库，只能算是把图跑通了。

**1. 抽出两个共用 service（不再复制逻辑）**

- `app/services/llm.py`：Ollama `/api/chat` 封装，`chat()` 返回 content / model / prompt_tokens /
  completion_tokens。对话和工作流共用这一份；`OPENAI_*` 仍未接（要接只改这个文件）。
- `app/services/retrieval.py`：把 `conversations.py` 里的本地关键词检索搬出来
  （`retrieve_chunks` / `build_rag_context`），对话与 RAG 节点共用同一套打分逻辑。

**2. 执行器新增两个节点**

- **LLM**：`config.prompt_template`（支持 `{{变量}}` 渲染）→ 调模型 → 输出 content / model / token 数；
  结果并进变量 `llm_output` / `llm_model`；每次调用写一条 `cost_records`
  （`operation_type=workflow_llm`，本地模型金额记 0、token 是真实的）。
- **RAG**：`config.knowledge_base_id` + `query_template` + `top_k` → 本地检索 → 输出 count / chunks
  （内容截断 200 字）；`rag_context` / `chunk_count` 并进变量，后面的 LLM 节点可以直接 `{{rag_context}}`。
- 失败信息落到节点级：例如没起 Ollama → 「调用模型失败：连不上 http://127.0.0.1:11434…」
  （提示检查 `OLLAMA_BASE_URL` / `OLLAMA_CHAT_MODEL`），执行记录 FAILED + ERROR 通知。

**3. 顺手修掉一个真 bug**

`/costs/summary` 以前**一有成本记录就 500**：`func.date()` 在 SQLite 返回字符串，代码直接
`.isoformat()`。成本表一直是空的所以没暴露，LLM 节点写入第一条记录后立刻炸出来。
现在统一用 `_iso_date()` 兼容字符串和 date 对象。

**验证（本机实跑，Ollama `qwen2.5-coder:1.5b` 在 11434）**：

```
ruff check services tests                       → All checks passed
pytest tests/test_gateway_smoke.py -q           → 20 passed
  · LLM 节点：COMPLETED、节点 content 非空、prompt_tokens>0、
    END 里能引用 llm_model、/costs/summary 出现 workflow_llm（37 tokens）
  · RAG 节点：新建知识库 + 上传文档 → 检索命中（count≥1、chunk 含关键词）、
    rag_context 进入 END 输出
  · 条件分支仍明确 FAILED「不支持 CONDITION」
两个冒烟文件                                     → 25 passed / 17 skipped
```

**未验证 / 已知限制**：

- LLM 节点只接了 Ollama；`OPENAI_*` 配置存在但没实现，配了 OpenAI Key 也不会走。
- RAG 节点是网关本地的关键词检索，不是向量检索（向量在 rag-service）。
- 工作流 LLM 调用金额记 0（本地模型没有单价），只统计 token。
- 条件分支 / 并行 / 合并仍要用 `GATEWAY_PROXY_WORKFLOWS=true` 走 workflow-service。
- 前端编辑器早就有 LLM / RAG 节点的配置面板，这一轮没改前端。

### 2026-11-26 · 第 29 轮：默认模式的工作流执行器（执行按钮不再是摆设）

**背景**：`POST /workflows/{id}/execute` 以前只插一条 PENDING 记录就返回（`# TODO: 发送到 workflow-service`），
前端点「执行」永远没有结果 —— 工作流只有建模、没有运行。真正的引擎在 workflow-service，但默认单体模式
不连它，所以这里补一个范围明确的最小执行器。

**1. `app/services/workflow_runner.py`（最小执行器）**

- 支持 **START / END / HTTP / DELAY**，沿出边线性执行。
- 预检节点类型：遇到 LLM / RAG / CONDITION / TRANSFORM / PARALLEL / MERGE **直接失败**并说明
  「要用 workflow-service」，不假装成功、也不留半成品。
- 图级校验：没有 START、多个 START、成环、出边多于一条（分支）都给明确错误。
- HTTP 节点真发请求（15s 超时、跟随重定向、响应 JSON 并进变量，后续节点可用 `{{field}}`）；
  DELAY 上限 10s；变量替换只做 `{{name}}` 字符串替换，行为可预测。

**2. 落库与通知**

- 执行记录：`RUNNING` → `COMPLETED` / `FAILED`，写 `output` / `error` / `completed_at` /
  `node_executions`（节点级 status / output / error / started_at / duration_ms）。
  时间存 ISO 字符串 —— JSONB 列不认 `datetime`，第一次实现就踩了这个 500。
- 复用第 28 轮的 `notify`：成功 → SUCCESS「工作流「名字」执行完成（N 个节点，X ms）」，
  失败 → ERROR 带具体原因。默认模式与转发模式都走同一个出口。

**3. 前端小修**

- 执行按钮以前不管结果都 toast「执行完成」；现在 `COMPLETED` 才 success，否则把 `error` 弹出来
  （否则新增的失败路径在界面上完全看不出来）。

**验证（本机实跑）**：

```
ruff check services tests                     → All checks passed
pytest tests/test_gateway_smoke.py -q         → 18 passed（新增 3 项）
  · START→END：status=COMPLETED、completed_at、node_executions=[start,end]、output 带回输入、
    执行历史里也能读到节点明细、通知 SUCCESS
  · LLM 节点：status=FAILED、error 里写明「不支持 … LLM」、node_executions 为空、通知 ERROR
  · HTTP 节点：真请求网关自己的 /health，节点 output.status_code=200，响应字段并进变量（END 里取到 healthy）
两个冒烟文件                                   → 23 passed / 17 skipped
apps/web tsc --noEmit                         → 0
```

**未验证 / 已知限制**：

- 只支持 4 种节点；LLM / 知识检索 / 条件分支仍然要用 `GATEWAY_PROXY_WORKFLOWS=true` 走 workflow-service。
- HTTP 节点**没有 SSRF 防护**：可以请求任意 URL（包括内网）；生产要加地址白名单 / 禁止私网。
- 同步执行：HTTP 慢会拖住这个请求（15s 超时），DELAY 上限 10s；异步执行仍需要队列。
- 执行历史页面只显示概要，节点明细已经入库但前端还没展开显示。

### 2026-11-26 · 第 28 轮：通知由业务事件产生（解析完成/失败、工作流执行结束）

**背景**：第 27 轮做完通知中心后，全仓库只有 `POST /notifications` 一处会写通知 —— 页面是空壳，
只能手工 curl 造数据。本轮把「业务事件 → 通知」接上，让通知中心有真实内容。

**1. 统一出口 `app/services/notify.py`**

- 独立 session 写、异常只 `logger.warning`：通知失败绝不影响上传/执行，也不会把调用方的事务拖回滚。
- 两种后端：`GATEWAY_PROXY_NOTIFICATIONS=false` 写网关自己的 `notifications` 表；打开时带
  `internal_headers()` 签名 POST 给 notification-service —— 否则列表已经转发，通知写完也没人看得到。
- `user_id` 为空直接跳过（列表按 `user_id` 过滤，写了也是死数据）。

**2. 接入的事件**

| 事件 | 位置 | 生成的通知 |
|---|---|---|
| 上传后解析完成（网关默认管线） | `documents.upload_document` | SUCCESS《文件名》解析完成（分块数 / tokens） |
| 解析失败（空文件、找不到原始文件等） | 同上 | WARNING《文件名》解析失败（带错误原因） |
| 重新解析（成功 / 失败） | `documents.reprocess_document` | SUCCESS / WARNING，标题带「重新」 |
| 转发模式「上传即解析」 | `proxy._upload_document` | SUCCESS / WARNING（解析在 document-service 侧，通知仍由网关发） |
| 工作流执行结束 | `proxy_workflows._execute` | completed → SUCCESS、failed → ERROR、cancelled → WARNING |

所有通知的 `data` 都带 `event` + 资源 id（`document_id` / `knowledge_base_id` / `workflow_id` /
`execution_id`），前端以后可以拿它做「点通知跳详情」。

**3. 测试**

- `tests/test_gateway_smoke.py` 新增 2 项（手搓 multipart，只依赖标准库）：上传 .txt → 通知标题带文件名、
  `data.document_id` 与上传返回一致、未读；上传空文件 → WARNING「解析失败」。用例结束会删掉自己的文档与通知，
  反复本地跑不会污染演示数据。
- `tests/test_microservices_smoke.py` 的 `test_gateway_forwards_workflows` 末尾补「执行 + 通知」断言
  （需要 workflow-service 与两个转发开关，未满足时整条用例本来就会 skip）。

**验证（本机实跑）**：

```
ruff check services tests                                  → All checks passed
默认模式 pytest tests/test_gateway_smoke.py -q             → 15 passed（新增 2 项）
默认模式 pytest 两个冒烟文件                                → 20 passed / 17 skipped
转发模式（notification-service 8006 + GATEWAY_PROXY_NOTIFICATIONS=true）
  pytest -k "upload_creates_notification or failed_parse"  → 2 passed
  （通知写进微服务，再经网关列表读回，证明两种后端都写对）
转发模式（document-service 8004 + GATEWAY_PROXY_DOCUMENTS=true）手工上传 .txt
  → 网关 /notifications 出现《proxy-smoke-xxx.txt》解析完成，data.document_id 一致
工作流（workflow-service 8005 + GATEWAY_PROXY_WORKFLOWS/NOTIFICATIONS=true）
  pytest -k gateway_forwards_workflows                     → 1 passed
  （执行完成后通知里能查到 workflow_id，type=SUCCESS）
```

**未验证 / 已知限制**：

- 默认模式的工作流 `execute` 只建一条 PENDING 执行记录（执行器仍是 TODO），所以「执行结束」通知
  只会在转发模式出现；默认模式下执行工作流不会产生通知，这是真实状态，没有伪装。
- 转发路径只给「上传即解析」补了通知：`reprocess`、删除等操作没有逐条补。
- 通知是同步写入：单条 insert 很快，但量大了应该改成队列 / 后台任务。
- 邮件 / Webhook 仍然只入库不外发（`status` 停在 `pending`）。

### 2026-11-26 · 第 27 轮：工作台通知中心（把第 26 轮的链路真正用起来）

**背景**：第 26 轮把 `/notifications` 接进了转发，但前端一条通知代码都没有——链路只被 pytest 碰过，
真实用户看不到任何通知。本轮补上工作台的「通知中心」，并顺手修掉两个挡住它的真 bug。

**1. 请求层与类型（`apps/web`）**

- `types/index.ts` 新增 `NotificationItem`（`id/tenant_id/user_id/type/channel/title/content/data/read/sent_at/created_at`）。
- `lib/api.ts` 新增 5 个方法：`getNotifications({ unread_only, limit })`、`getUnreadNotificationCount()`、
  `markNotificationRead(id)`、`markAllNotificationsRead()`、`deleteNotification(id)`。
  分页仍走 `toPageParams`（`limit` → `page_size`），列表沿用拦截器的信封解包（`data.items` 摊平成数组）。

**2. 页面与入口**

- `app/notifications/page.tsx`：列表 + 「全部 / 未读」筛选 + 逐条「标记已读」+ 删除 + 「全部已读」+ 刷新；
  未登录给「请先登录」（和 `/workflows` 一致，不再永远转圈）；空态、加载态、错误提示齐全。
- `components/notifications/notification-bell.tsx`：导航栏铃铛（仅登录后显示），未读数徽标 + 最近 6 条 +
  「全部已读」+「查看全部通知」。加载失败静默降级，不影响导航栏其余部分。
- `components/navbar.tsx`：铃铛放在「智能助手」与用户菜单之间。

**3. 顺手修掉的两个真 bug**

- `lib/api.ts` / `next.config.js` 的 `NEXT_PUBLIC_API_URL` 兜底值写成了 **8200**，而网关是 **8000**。
  本机因为有 `apps/web/.env.local` 覆盖才碰巧能跑；CI 或新克隆没有这个文件时，所有请求会打到空端口。
  已把两处兜底值改成 8000。
- 网关 `POST /api/v1/notifications` 不传 `user_id` 时直接写 `None`，而列表按 `user_id` 过滤 —— 这条通知
  **谁也看不到**（转发模式下 notification-service 是「默认发给自己」，两边行为不一致）。改成
  `user_id=notif_data.user_id or current_user.id`。这个 bug 是写 E2E 时「创建成功但列表里没有」暴露出来的。

**验证（本机实跑）**：

```
pnpm --filter @enterprise-ai/web run typecheck   → 0
pnpm --filter @enterprise-ai/web run test        → 45 passed（新增 4 项通知请求层用例）
pnpm --filter @enterprise-ai/web run lint        → 0（仅历史 exhaustive-deps warning）
pnpm --filter @enterprise-ai/web run build       → 0，路由表出现 ○ /notifications（2.9 kB / 124 kB）
网关 8000（默认模式）+ apps/web playwright test  → 9 passed（新增 2 项：未登录提示；造数据→已读→删除）
pytest tests/test_microservices_smoke.py tests/test_gateway_smoke.py → 18 passed / 17 skipped
  （默认模式没开转发、没设 SERVICE_API_KEY，转发相关 2 项自动 skip，属预期）
```

**未验证 / 已知限制**：

- 转发模式（`GATEWAY_PROXY_NOTIFICATIONS=true`）下没重跑前端页面；契约两侧一致（第 26 轮已验证），
  但「前端 + 微服务」组合没有截图/手点。
- 没有做「新通知实时推送」：铃铛只在挂载和打开下拉时拉一次，页面没有轮询/WebSocket。
- 通知的创建入口仍只有 API（ADMIN），前端没有「发通知」表单；邮件 / Webhook 真正发送仍是 TODO。

### 2026-11-26 · 第 26 轮：notification-service 接入网关转发（先把契约对齐）

**背景**：第 16 轮把通知列为「不可拆」：网关是 UUID 主键 + `user_id/title/data/read`，
notification-service 是 `int` 主键 + `recipient_id/subject`，假造 UUID 会让已读/删除按 ID 找不到记录。
Backlog 里这条一直挂着，要求先定数据归属。本轮选定 **数据归 notification-service、服务侧改契约**
（网关与前端不动），然后把 `/notifications` 接进转发。

**1. notification-service 改契约（迁移 `002_gateway_contract`）**

- 模型：`id` 改成 UUID；新增 `tenant_id` / `user_id`（UUID）/ `type` / `title` / `data` / `read`，
  保留服务侧的 `recipient_id`（邮箱、webhook URL）/ `recipient_type` / `status`（投递状态）。
- 迁移策略「先建新表 → 拷数据 → 删旧表 → 改名」：SQLite 的 DDL 不是事务性的，
  直接在原表上 drop/create 一旦拷贝失败数据就没了。拷贝时把 UUID 形态的 `recipient_id` 写进 `user_id`，
  `subject` → `title`（空则取正文首行），`status == "read"` → `read = true`。**行 ID 会变**（自增整数无法映射）。
- 新增 `app/core/context.py`：从 `X-Tenant-Id` / `X-User-Id` 取身份（非法 UUID → 400），
  所有列表/已读/删除都限定在当前用户，直连 8006 也读不到别人的通知。
- API：`GET /notifications`（page/page_size/unread_only/type + `X-Total-Count`）、
  `GET /unread-count`、`PATCH /read-all`、`PATCH|POST /{id}/read`、`DELETE /{id}`；
  旧的 `recipient_id` 过滤与 `subject` 入参仍然兼容（微服务冒烟一直在用）。

**2. 网关侧转发**

- 新增 `GATEWAY_PROXY_NOTIFICATIONS`（默认关）与 `NOTIFICATION_SERVICE_URL`；
  `proxy_notifications.py` 注册在网关自带 notifications 路由**之前**，字段映射在
  `proxy_adapters.to_gateway_notification()`，不再伪造 ID。
- 权限与网关原路由一致：列表/已读/删除登录即可，**创建要求 ADMIN / SUPER_ADMIN**；
  网关本来没有的 `GET /notifications/{id}` 在转发模式返回 501。
- 未读数、`read-all`、`PATCH /{id}/read`（返回更新后的通知本体）都已对齐。

**验证（本机实跑）**：

```
ruff check services tests                        → All checks passed
迁移（临时库，先升 001 造 2 行旧数据，再升 head）  → 2 行全部保留：UUID 主键、user_id 解析、
                                                     subject→title、read 映射；alembic check 无漂移
真实开发库 notification.db（18 行旧数据）启动服务   → 自动升到 002，18 行全部保留
pytest tests/test_microservices_smoke.py -k "notification or ready"
  → 3 passed（新增 test_gateway_forwards_notifications + 原 test_notification_create_list_read + ready）
pytest tests/test_gateway_smoke.py                → 13 passed（转发开启时也不回归）
隔离抽查：换一个随机 X-User-Id 直连 8006 → total=0；X-Tenant-Id 非 UUID → 400
默认模式（开关关）GET /api/v1/notifications → 无 X-Gateway-Proxy 头，仍是网关自己的实现
```

**未验证 / 已知限制**：

- 邮件 / Webhook 真正发送仍是 TODO（本轮只改数据契约与转发，`status` 停在 `pending`）。
- 开关打开后网关自己的 `notifications` 表不再写入，两套数据不互通（与文档/工作流一致）。
- llm-service、rag-service 仍未接（原因见 `service-split.md` §5.2 / §5.3）。

### 2026-11-26 · 第 25 轮：`release` job 真正可用（装 changesets + 修两处硬伤）

**背景**：第 22 轮留下的 P2 —— `release` job 里用的 `pnpm changeset` 既没装 `@changesets/cli`，
也没有 `.changeset/`；而且只在 `main` push 时才会暴露，所以一直没人发现。

**1. 装 CLI + 建配置**

- 根 `devDependencies` 加 `@changesets/cli@^3.0.3`（唯一 lockfile 不变，`pnpm install --frozen-lockfile` 仍 exit 0）。
- 新建 `.changeset/config.json`：`baseBranch: main`、`changelog: @changesets/cli/changelog`、
  `access: restricted`、**`privatePackages: { version: true, tag: false }`** —— `apps/*` 全是 `private: true`，
  默认 changesets 会直接忽略它们；这个开关让它们参与版本号与 CHANGELOG，但仍然不发 npm。
- 新建 `.changeset/README.md`（怎么写 changeset）与一条真实 changeset `.changeset/admin-e2e-tests.md`
  （`@enterprise-ai/admin: patch`，第 23–24 轮的 E2E 与登出修复）。

**2. 修 `release` job 的两处硬伤**

- `Generate changelog` 步骤把 `echo "CHANGELOG<<EOF" >> $GITHUB_ENV`、`pnpm changeset status || echo … >> $GITHUB_ENV`
  与 `echo "EOF"` 混在一起：既把 `|| echo` 的输出当成 heredoc 内容，又把坏值写进 `GITHUB_ENV`。
  改成一行 `pnpm changeset status || echo "::notice::没有待发布的 changeset"`。
- action 里写了 `publish: pnpm changeset publish` + `NPM_TOKEN`：apps 都是 private 包，`changeset publish`
  不会发布它们，但没有 npm token 时这步会直接失败。改成只 `version: pnpm changeset version`
  + `commit/title: chore: version packages`，不再需要 `NPM_TOKEN`。

**验证（本机实跑）**：

```
pnpm install --frozen-lockfile      → 0（lockfile 已同步）
临时 git 仓库（已删）里跑：
  changeset status                  → Packages to be bumped: patch @enterprise-ai/admin，exit 0
  changeset version                 → admin 0.1.0 → 0.1.1，生成 apps/admin/CHANGELOG.md，web 不动
  再跑一次 status（已无 changeset） → exit 1（CI 已用 || echo 兜住，不会卡住发版）
ci.yml yaml.safe_load               → release job 6 步：… / Check changesets / Create Release PR
```

**未验证 / 已知限制**：

- GitHub Actions 仍未真实触发；`changesets/action@v1` 开 PR 需要仓库设置里允许
  「Allow GitHub Actions to create and approve pull requests」，否则只会报错。
- 本机这个项目目录**不是 git 仓库**，直接跑 `pnpm changeset status` 会报
  `Failed to find where HEAD diverged from "main"`（正常，`status` 依赖 `main` 分支）；上面的验证是在临时
  git 仓库里做的。
- `docker-build` job 仍未验证（本机 Docker 守护进程未启动）。

### 2026-11-26 · 第 24 轮：E2E 进 CI（admin 8 + web 7），并给 E2E 加 60s 超时

**背景**：第 23 轮把 admin E2E 做出来了，但 `ci.yml` 里只有单测，E2E 只在本地跑；
Backlog 里记的 P2 就是这条。

**做法**：

- 新增 `e2e-tests` job（14 步）：checkout → pnpm / Node 20 → Python 3.11 → `pnpm install --frozen-lockfile`
  → 装网关 `requirements.txt` → `pnpm --filter @enterprise-ai/admin exec playwright install --with-deps chromium`
  → SQLite 起网关（复用 `smoke-tests` 的启动脚本，轮询 `/health` 最多 120s）
  → **前置门禁：curl 演示账号登录必须 200** → 跑 admin E2E → 跑 web E2E
  → 失败时上传 `apps/*/test-results`、`apps/*/playwright-report` 并打印网关日志 → `always()` 停网关。
- 为什么加「登录必须 200」这一步：E2E 里网关不可用会 `test.skip`，只跑 `playwright test` 的话
  后端没起来 job 也是绿的（假绿）。
- `build` 的 `needs` 加上 `e2e-tests`：E2E 不过不再继续构建。
- 两个 app 的 `playwright.config.ts` 加 `timeout: 60_000`：CI 上 `next dev` 首次访问要现场编译，
  默认 30s 不够（本地 4–10s 看不出来）。

**验证**：

```
YAML yaml.safe_load       → 11 个 job，e2e-tests 14 步，build.needs 含 e2e-tests
本机按 job 命令实跑      → 网关 3s healthy、演示账号登录 200
  admin playwright test   → 8 passed (20.9s)
  web   playwright test   → 7 passed (19.8s)
```

**未验证**：GitHub Actions 本身仍未真实触发（仓库没有远端）；`playwright install --with-deps` 的
apt 依赖、ubuntu runner 上 `next dev` 首次编译耗时都只是按经验预留了 60s 超时。

### 2026-11-26 · 第 23 轮：管理后台 E2E（8 项）+ 修「退出登录失败后界面仍显示已登录」

**背景**：第 21 轮给 `apps/admin` 补了 28 项单测，但 Backlog 里「admin 仍无 E2E」一直空着
（工作台第 7 轮就有 7 条 Playwright 用例）。本轮把后台也纳入 E2E，写用例的过程中抓到一个真实状态 bug。

**1. 新增 `apps/admin` 的 Playwright 配置与 8 条用例**

- `playwright.config.ts`：端口 **3001**（与 `pnpm dev` 一致）、只跑 chromium、`webServer` 自动起前端；
  与 web 一致，依赖接口的用例先探测网关 8000，没起就 `test.skip`（不制造假绿）。
- `tests/e2e/support.ts`：`backendIsUp()` + `loginAsAdmin()`（`#email` / `#password` / 登录按钮 / 等「总览」标题）。
- `tests/e2e/auth.spec.ts`（4 项）：未登录只渲染登录表单（不暴露导航与总览）、密码错误给出可读错误且不写 token、
  正确账号登录后出现导航 + `aria-current="page"` + 刷新仍是登录态、退出后清 token 回到登录表单。
- `tests/e2e/navigation.spec.ts`（4 项）：五个导航项逐个打开并校验标题与 `aria-current`、
  「跳到主内容」+ `main#main` 地标、用户页搜索空态与恢复、审计「查看」按钮打开明细对话框并关闭
  （第 20 轮把整行 `onClick` 改成按钮，这条用例从此有回归保护）。
- `package.json` 补 `@playwright/test` / `playwright`（与 web 同版本范围）与 `e2e` / `e2e:ui` / `e2e:headed`；
  `.gitignore` 补 admin 的 `test-results/`、`playwright-report/`。

**2. 用例暴露的真 bug：登出失败会留下「界面已登录、请求全 401」**

- 首轮 8 个 worker 并行跑时，「退出后清掉会话」稳定失败：点「退出」后页面还停在后台 Shell 里，
  而 `access_token` 已经被删掉。
- 根因在 `apps/admin/lib/auth.tsx`：`await api.logout(); setUser(null);` —— `api.logout()` 在 `finally` 里清 token，
  但**会把请求异常继续抛出**；后端 500 / 不可达（本地 SQLite 并发写锁就会 500）时 `setUser(null)` 根本不执行。
- 修法：`logout()` 改成 `try { await api.logout() } catch {} finally { setUser(null); setTenant(null) }`。
- 补 6 项单测 `tests/unit/auth-provider.test.tsx`（unmock `@/lib/auth`、给 `@/lib/api` 换可编程替身）：
  无会话不拉 `/auth/me`、有会话恢复用户、`me()` 失败退回未登录、非管理员登录被拒并撤销会话、
  **登出失败仍清空身份**、正常登出清空身份。

**3. 用例本身踩的两个坑（已修，别再踩）**

- `test.skip(!backendUp)` 写在 `describe` / 文件作用域会在**收集阶段**求值，那时 `beforeAll` 还没跑，
  `backendUp` 恒为 false → 整组静默跳过（首轮 4 项 skipped 就是这个原因）。必须写在用例体内。
- Next dev 页面自带一个空的 `role="alert"`（`__next-route-announcer__`），`getByRole('alert')` 在 strict mode 下
  会命中两个元素；断言登录错误要限定 `p[role="alert"]`，否则「只断言可见」还会假绿。

**验证（本机实跑）**：

```
cd apps/admin && ./node_modules/.bin/playwright test   → 8 passed (9.9s)
./node_modules/.bin/vitest run                          → 4 files / 34 passed
pnpm lint                                               → 0（5 tasks）
pnpm typecheck                                          → 0（5 tasks）
pnpm test                                               → 0（web 41 + admin 34 = 75 passed）
pnpm build                                              → 0（5 tasks，两个 next build 都过）
```

- 跑 E2E 前先在 `services/api-gateway` 起网关（`/health` 200），结束后用 `taskkill //F //T //PID` 停掉
  自己起的 3001 dev server，端口无残留。

**未验证 / 已知限制**：

- `apps/admin` 的 E2E **没进 CI**（`ci.yml` 只有单测 job；Playwright 要先起网关，与 `smoke-tests` 同类问题）。
- 只跑了 chromium；firefox / webkit 未纳入门禁（与 web 一致）。
- E2E 跑在 SQLite 演示库上，会写登录审计；CI 里 worker 必须保持 1
  （`workers: process.env.CI ? 1 : undefined`），否则 SQLite 写锁会放大偶发 500。

### 2026-11-25 · 第 22 轮：改成真正的 pnpm workspace，CI 安装/lint/typecheck/test/build 全部本地跑通

**背景**：第 21 轮发现 CI 的第一步 `pnpm install --frozen-lockfile` 根本不可能成功（根目录没有
`pnpm-workspace.yaml` / `pnpm-lock.yaml`，只有各 app 各自的子锁文件），且 `turbo.json` 还是 turbo 1.x 的
`pipeline` 字段。本轮把这条 P1 做掉，目标是「干净目录下 `pnpm install --frozen-lockfile && pnpm lint &&
 pnpm typecheck && pnpm test && pnpm build` 全绿，且两个前端的 dev server 仍能起」。

**1. 仓库改成单一 pnpm workspace**

- 新增根 `pnpm-workspace.yaml`：只收 `packages/*` 与 `apps/*`（`services/*` 是 Python，没有 `package.json`，不能放进来，
  否则 turbo 会把它们当 workspace 包）。根 `package.json` 里 pnpm 不认的 `workspaces` 字段删掉。
- 删掉 `apps/admin/pnpm-lock.yaml`、`apps/web/pnpm-lock.yaml` 与两个子 `node_modules`，在根重新生成一份
  `pnpm-lock.yaml`（728 个包，pnpm 9.15.9）。之后依赖只有一份，`pnpm install --frozen-lockfile` 可复现。
- `turbo.json`：`pipeline` → `tasks`（turbo 2.11.13 要求）；`test` 的 `dependsOn` 从 `["build"]` 改成 `["^build"]`
  —— 原来的写法会在跑单测前先 `next build` 两个 app，既慢又会因为构建产物覆盖 `.next` 打断 dev。
- 两个 app 补 `typecheck` 脚本（原来只有 `type-check`，turbo 的 `typecheck` 任务会跳过它们，等于 CI 的类型检查
  只覆盖 packages）。

**2. 安装/构建链路上三个真实的坏点（都是被这次迁移暴露出来的）**

- `packages/ui-components` 依赖了 npm 上**不存在**的 `@radix-ui/react-button` / `@radix-ui/react-input`，
  直接让 `pnpm install` 404 退出。前者没有任何代码引用，删掉；`Input.tsx` 原本 `import * as InputPrimitive from
  '@radix-ui/react-input'`，改成原生 `<input>` + 同样的 `className`（Radix 从来没有 input 原语）。
- `packages/shared-types` 有 `test: vitest run` 但 `tests/` 是空的，`vitest run` 无测试文件退出码 1，
  会让 `pnpm test` 必红 → 改成 `vitest run --passWithNoTests`。
- `pnpm lint` 完全是坏的：根 `.eslintrc.js` 引用的 `@typescript-eslint/*`、`eslint-plugin-react*`、
  `eslint-plugin-prettier`、`eslint-plugin-import`、`eslint-plugin-unused-imports`、`eslint-import-resolver-typescript`
  以及 `.prettierrc` 里两个 prettier 插件**一个都没装**。补齐 root devDeps 后：
  - `.eslintrc.js` 测试文件 override 里的 `extends: ['plugin:vitest/recommended']` 会触发
    `TypeError: Converting circular structure to JSON`（eslint-plugin-vitest 0.5 + .eslintrc 的已知问题），
    改成只保留 `env: jest/node` + `globals: { vi, vitest }`，插件依赖一并移除。
  - `apps/admin` 没有 `.eslintrc.json`，`next lint` 会尝试交互式初始化 → 补一份与 `apps/web` 相同的配置。
  - 剩下的 8 处真实告警手工修：`packages/config` 3 处 `||`→`??`（`ENV_FILE`、celery broker/backend）、
    `Button` 的 `disabled || loading` → `loading || Boolean(disabled)`（不能直接用 `??`，`disabled=false` 会被当成
    有值而忽略 `loading`）、`kebabToCamel` 的回调参数补类型、`deepClone` 的 `JSON.parse` 补 `as T`。

**3. CI 里跟 workspace 相关的收尾**

- `unit-tests` job 原来是 `pnpm test -- --coverage`：pnpm 会把 `--` 吃掉，turbo 收到裸的 `--coverage` 直接
  `unexpected argument`；而且 `@vitest/coverage-v8` 根本没装、vitest 默认 reporter 也不产 `lcov.info`。
  现在根加了 `test:coverage`（`turbo run test:coverage`），两个 app 各加 `vitest run --coverage`、依赖补
  `@vitest/coverage-v8@1.6.1`、`vitest.config.ts` 的 reporter 补 `lcov`；CI 改跑 `pnpm test:coverage`，
  codecov 收 `apps/*/coverage/lcov.info`。
- `security-scan` job 里 `pnpm install`/`pnpm audit` 之前没有 setup-node / setup-pnpm 步骤（runner 上没 pnpm），补上。

**验证（全部在本机实跑，用的就是 CI 的命令）**：

```
pnpm install --frozen-lockfile   → 0（Lockfile is up to date）
pnpm lint                        → 0（5 packages，admin/web next lint 也干净）
pnpm typecheck                   → 0（5 tasks）
pnpm test                        → 0（web 41 + admin 28 = 69 passed，shared-types 无用例跳过）
pnpm test:coverage               → 0，产出 apps/web/coverage/lcov.info、apps/admin/coverage/lcov.info
pnpm build                       → 0（5 tasks，两个 next build 都过）
```

- dev server：`pnpm --filter @enterprise-ai/admin run dev`（3001）与 `--filter @enterprise-ai/web run dev`（3002）
  都能 `Ready`，`GET /` 均 200（admin 5.1s / web 5.4s 首编译），验证完已用 `taskkill /T` 停掉，端口无残留。
- `.github/workflows/ci.yml` 用 `yaml.safe_load` 解析通过，`security-scan` 步骤里已有 `Setup pnpm` / `Setup Node.js`。

**未验证 / 已知限制**：

- GitHub Actions 仍未真实触发（仓库没有远端），本机是 Windows + Node 24；CI 是 ubuntu + Node 20，
  `pnpm install --frozen-lockfile` 的平台相关 optional 依赖（如 `@next/swc-*`）理论上由 lockfile 覆盖，但没在 Linux 上验过。
- `apps/web` 仍有 `@testing-library/jest-dom@6.10` 与 `@testing-library/dom@9`（RTL 14 的依赖）的 peer 警告，
  只是 warning，41 项用例照常通过，没动。
- `docker-build` / `release` 两个 job（dockerfile 与 changesets）仍未验证，且 `release` 用的 `pnpm changeset`
  既没装 `@changesets/cli` 也没有 `.changeset/`，只在 `main` push 时才会暴露。

### 2026-11-25 · 第 21 轮：管理后台单测 + CI 真正启动后端跑冒烟

**背景**：第 20 轮清完 P2 后，Backlog 里剩下的测试类缺口是「`apps/admin` 没有单测/E2E」和
「CI 里的后端用例需要先起服务，否则只能是 skip」。本轮把这两条里能自洽验证的部分做掉。

**1. `apps/admin` 有了单测（28 项，vitest + jsdom）**

- 新增 `vitest.config.ts`（alias 与 `tsconfig` 的 `@/*` 对齐）、`tests/unit/setup.tsx`
  （mock `next/link`、`next/navigation`、`@/lib/auth`、`@/lib/api`，组件测试不会真发请求）。
- `tests/unit/api-client.test.ts`（14 项）：axios 用可编程替身但**真的执行 api.ts 注册的拦截器**，覆盖
  Bearer 头、`{success,data}` 信封解包、`skip/limit → page/page_size`、审计 `page_size ≤ 100`、
  `display_name → full_name` / `status → is_active` 映射、后端 `error.message` / FastAPI `detail`（字符串与数组）
  转 `ApiError`、401 清本地 token、登录写入 token、登出失败也清 token、`hasSession`。
- `tests/unit/utils.test.ts`（8 项）：`cn` 冲突类合并、`formatBytes` / `formatNumber` / `truncate` / `getInitials`、
  `parseError` 四种输入、`isValidUrl`、`formatRelativeTime` 各档位。
- `tests/unit/auth-gate.test.tsx`（6 项）：加载态 `role="status"`、未登录渲染登录表单、
  登录失败用 `role="alert"` 显示后端文案、已登录有「跳到主内容」链接 + `<main id="main">`、
  当前导航 `aria-current="page"`、退出按钮调 `logout`。第 20 轮的可访问性改动从此有回归保护。
- 依赖按 `apps/web` 的既有版本对齐（`vitest@1.6.1`、`@vitejs/plugin-react@4.3.4`、`jsdom@24.1.3`、
  `@testing-library/react@14.3.1`、`@testing-library/jest-dom@6.10.0`、`@testing-library/user-event@14.6.13`），
  `package.json` 新增 `test` / `test:watch`。

**2. CI 新增 `smoke-tests` job：真实启动网关再跑冒烟**

- 原来 `tests/test_gateway_smoke.py` 只在本地跑，CI 里没有任何地方启动网关；
  现在 job 用 SQLite 起 `uvicorn app.main:app`（`DB_AUTO_MIGRATE=true`），轮询 `/health`（最多 120s），
  再跑 `pytest tests/test_gateway_smoke.py -q`，失败时打印 `/tmp/gateway.log`，最后 `always()` 停进程。
- 顺手修了 `python-tests` job 的必然失败：`services/{rag,llm,document}-service/tests` 三个目录**是空的**，
  `pytest 空目录` 退出码是 5，整个 job 必红；现在用 `compgen -G` 判断有没有 `test_*.py`，
  没有就 `::notice::` 跳过，并补装 `requirements-dev.txt`（原 job 连 pytest 都没装）。
- `build` 的 `needs` 加上了 `smoke-tests`，冒烟不过不再继续构建。

**验证**：

- `apps/admin`：`./node_modules/.bin/vitest run` → **3 files / 28 tests passed**；`tsc --noEmit` 通过（测试文件也在 `include` 里）。
- 本地按 CI 的同一串命令跑：网关 4 秒就绪 → `pytest tests/test_gateway_smoke.py -q` → **13 passed**，
  结束后进程已停、8000 端口只剩 `TIME_WAIT`。
- `.github/workflows/ci.yml` 用 `yaml.safe_load` 解析通过，`jobs` 里能看到 `smoke-tests`。

**未验证 / 已知限制**：

- GitHub Actions 本身没跑过（没有远端仓库可触发），CI 只做了 YAML 解析与命令本地复现。
- 发现两个**会挡住 CI 安装阶段**的既有问题，本轮没动（改动面大且会影响本地安装方式），已记进 Backlog：
  根目录既没有 `pnpm-workspace.yaml` 也没有 `pnpm-lock.yaml`，CI 的 `pnpm install --frozen-lockfile` 必失败；
  `turbo.json` 仍用 1.x 的 `pipeline` 字段，turbo 2 要求 `tasks`。
- `apps/admin` 仍没有 E2E；微服务冒烟（需要 6 个服务同时起）也仍未进 CI。

### 2026-11-25 · 第 20 轮：5 个服务改 Alembic、k8s 清单可渲染、管理后台可访问性回归

**背景**：第 19 轮留下的三条 P2 —— 5 个服务启动仍 `create_all`、`infra/k8s` 与实际服务名/端口不一致、
管理后台没做过对比度/键盘/窄屏回归。

**1. 其余 5 个服务的启动建表改为 Alembic**（都保留 `DB_AUTO_MIGRATE=false` 退回 `create_all` 的口子）

- `auth / notification / document / llm / workflow` 的 `app/db/session.py` 统一为：
  有 `alembic_version` 就 `upgrade head`；有表但没有版本表则先 `stamp head` 再 upgrade（打印警告，不校验列差异）。
- 探表用 **async 引擎**（`create_async_engine` + `run_sync(inspect)`）而不是同步 `create_engine`：
  这些服务只装 `asyncpg` / `aiosqlite`，没有 `psycopg`，第 18 轮就是在这里踩过 `ModuleNotFoundError`。
- 迁移在 `asyncio.to_thread()` 里跑（Alembic 自己会 `asyncio.run`，不能在已运行的事件循环里直接调）。
- `DB_AUTO_MIGRATE` 字段加进 5 个服务的 config（默认 true），语义与网关 / rag 一致。
- 实测：5 个服务空库 `init_db()` 建出全表 + `alembic_version=001_initial_schema`；
  再造一个「有表无版本表」的旧库，启动时按预期 `stamp head` 后 upgrade；本地已有的 5 个 SQLite 开发库启动后也都带上了版本号。

**2. rag embedding 错误映射补上构造阶段（测试暴露的真 bug）**

- `AsyncOpenAI(api_key="")` 在**构造时**就抛错，而三处构造都在 `try` 之外 →
  没配 `EMBEDDING_API_KEY` 时返回 **500**，与第 8 轮约定的「503 + 可读文案」不符。
- 已把 `document_processor._get_embedding_client`、`retrieval._embed_query`、`POST /embeddings` 的构造搬进 `try`，
  统一映射为 `EmbeddingUnavailable` → 503。

**3. `infra/k8s` 与真实服务名/端口对齐**

- 新增 `auth-service`（8007，`PORT=8007`，`JWT_SECRET_KEY` 复用 Secret 的 `JWT_SECRET`）与
  `notification-service`（8006）的 Deployment/Service，加进 `base/kustomization.yaml` 和三个 overlay 的 image tag。
- 修真实错配：admin 容器实际监听 **3000**（Dockerfile `ENV PORT=3000`），清单与 ingress 原来写 3001；
  网关 readiness 指向不存在的 `/ready` → 改 `/health/ready`（liveness 用 `/health/live`）。
- ConfigMap 补 `DB_AUTO_MIGRATE` 与 `AUTH/DOCUMENT/RAG/LLM/WORKFLOW_SERVICE_URL`
  （网关默认值指向 `127.0.0.1:xxxx`，进集群即失效）；Secret 补 `SERVICE_API_KEY`。
- 顺手修好**一直无法渲染**的 overlay：`configMapGenerator` / `secretGenerator` 的 merge 目标要写 `namespace: enterprise-ai`，
  且 overlay 不能再设 `namespace:`（会把 base 里的 `monitoring` Namespace 一起改名 → ID 冲突）。
- 验证：`kubectl kustomize infra/k8s/overlays/{dev,staging,prod}` 三个都 exit 0，各 34 个资源；
  渲染结果里 admin `containerPort=3000`、网关探针 `/health/live` + `/health/ready`、auth `8007` + `PORT=8007`、notification `8006`。

**4. 管理后台视觉/可访问性回归（`apps/admin`）**

- 对比度：`--primary` 48%→36%（白字蓝底 2.8:1 → 4.9:1）、`--destructive` 60%→45%、`--muted-foreground` 46.9%→40%；
  dark 主题把 `--destructive` 提亮到 60%，否则深色底上的错误文字看不清。
- 键盘：全局 `:focus-visible` 描边；顶部「跳到主内容」跳转链接；`<main id="main">` 地标；导航 `aria-label` + `aria-current="page"`。
- 语义：表头 `scope="col"`；加载态 `role="status"`；错误提示 `role="alert"`；预算进度条 `role="progressbar"` + `aria-value*`。
- 审计表格原来整行 `onClick`（键盘不可达）→ 改成「查看」按钮，行本身不再可点。
- 图标按钮（用户编辑/删除、租户重命名）补 `aria-label` / `title`，装饰性图标 `aria-hidden="true"`。
- 窄屏：头部 `min-h-16 + flex-wrap`，导航可横向滚动。
- 验证：`tsc --noEmit` 通过、`next build` 通过（10 个路由全部预渲染）。

### 2026-11-24 · 第 19 轮：CI 接入 ruff，顺手修了两个真 bug

**背景**：CI 里原本只有 Node 侧的 lint/typecheck，Python 代码没人管；
`ruff check` 一跑就报了 175 个问题，其中 3 个是会在运行时出错的。

**规则选择**（仓库根 `ruff.toml`，显式写死，不依赖开发者本机的用户配置）：

- `select = ["E4", "E7", "E9", "F"]`：只管硬错误（未定义名、未使用 import/变量、语法/语句级错误）；
- 不开 `UP/B/I` 等风格类规则——一次性改 1000+ 行是重构，不是本项目标；
- 显式忽略两类：
  - `E712`（`== True`）：SQLAlchemy 过滤器里必须这么写，改成布尔表达式会变成 `WHERE false`，ruff 的建议在这里是错的；
  - `E402`（导入不在文件顶部）：为了避开循环导入，FastAPI 项目里大量使用函数内导入，属有意为之；
- `per-file-ignores`：`__init__.py`（再导出）、`alembic/env.py`（导入模型是为注册 metadata，副作用导入）、`tests/*.py`。

**修出来的真 bug（不是风格问题）**：

1. `services/api-gateway/app/services/ingest.py`：本地解析完成后重算 KB 计数时用了 `select(...)`，
   但 `select` 从未导入 → `NameError`。这条路径在“网关本地入库”成功后必走，只是之前没覆盖到。
2. `services/api-gateway/app/api/v1/knowledge_bases.py` 的 `/stats`：循环变量写成了 `status`，
   遮蔽了模块级的 `fastapi.status`，Python 会把它当成函数局部变量 →
   “知识库不存在”分支抛 `UnboundLocalError` 而不是 404。已重命名为 `doc_status`。
3. 其余：`F811` 重复导入、`F841` 未使用赋值（rag / document 里无用的计时变量、workflow 里未用的 `node_map`）、
   `E741` 歧义变量名 `l`。

**清理量**：119 个未使用 import（`ruff --fix` 安全修复）+ 手工 13 处；最终 `ruff check services tests` 零告警。

**CI**：新增 `python-lint` job（安装 `requirements-dev.txt` → `ruff check services tests`），
并加入 `build` 的 `needs`，与 Node lint 同级卡门禁。

**验证**：ruff 零告警；四个服务重启后无 ImportError；微服务冒烟 **21 项 OK（skipped=3）**、网关冒烟 **13/13 OK**。

**备注**：C 盘的机器上存在用户级 ruff 配置（默认开了 YTT/ASYNC 等全部规则），
第一次统计才会出现 438 个 `UP045`。仓库级 `ruff.toml` 覆盖它，CI 与本机结果因此一致。

### 2026-11-24 · 第 18 轮：Alembic baseline 真正可用（7 个库全部 `upgrade head` + `check` 干净）

**先说结论**：仓库里那 7 份 `001_initial_schema.py` 之前**从未成功执行过一次**。本轮把发现的 6 类硬伤全部修好，
并把网关 / rag 的启动建表从 `create_all` 换成迁移。

| # | 问题 | 影响 |
|---|---|---|
| 1 | 网关 baseline 用了 `op.create_enum(...)` | Alembic 没有这个 API（来自第三方插件），`upgrade` 立刻 `AttributeError` |
| 2 | 7 个服务都缺 `alembic/script.py.mako` | `alembic revision` 直接 `FileNotFoundError`，无法新增迁移 |
| 3 | `env.py` 把 `+asyncpg` 换成同步 URL | Linux 上 `ModuleNotFoundError: psycopg`；Windows 上 psycopg 异步模式不支持 ProactorEventLoop |
| 4 | auth / notification 的 `alembic.ini` 有裸 `%` 与 `%(DATABASE_URL)s` | `InterpolationSyntaxError`，连配置都读不进来 |
| 5 | auth / notification 的 `env.py` 没导入模型 | `Base.metadata` 为空，`alembic check` 要求删掉所有表 |
| 6 | document / llm / workflow baseline 对 SQLite 用 `ALTER ADD CONSTRAINT`；rag 小写枚举名 + 缺 `vector` 扩展 | SQLite 报 `NotImplementedError`；rag 报 `type "vector" does not exist`，且枚举与实际模型/生产库不一致 |

**做法**：

- 网关 baseline 用模型 autogenerate 重新生成（可移植的 `GUID/JSONType/InetType`），补齐 `render_item` 让自定义类型自动带 import；
- document / llm / workflow 同样重建 baseline（保留原 revision id `001_initial_schema`）；
- rag 手工修正：`CREATE EXTENSION IF NOT EXISTS vector`、枚举 `documentstatus` + 大写标签（与生产库 `pg_enum` 完全一致）；
- auth / notification 修 ini（ASCII 注释，`version_path_separator = os`）并在 `env.py` 导入模型；
- 新增 `DB_AUTO_MIGRATE`（默认 true）：网关与 rag 启动时 `alembic upgrade head`，
  旧库（有表但无 `alembic_version`）先 `stamp head` 再升级，日志显式警告「不校验结构差异」；
- 网关补 `psycopg[binary]>=3.1.0` 依赖：`SYNC_DATABASE_URL` 在导入期就会 `create_engine`，
  Postgres 下没有它连服务都起不来（`get_sync_db` / Celery 也需要）。

**验证（真实执行，不是只看代码）**：

- 每个服务：空库 `alembic upgrade head` → `alembic check` = `No new upgrade operations detected`（7/7）。
- Postgres 上单独验证网关（18 张表）与 rag（4 张表 + `vector` 扩展），都无 drift。
- 网关旧库启动：自动 `stamp 001` 后正常启动，`test_gateway_smoke.py` **13/13 OK**。
- rag 旧库启动：日志出现「已有表但没有 alembic_version，直接 stamp head」，`/ready` 200，版本落 `001_initial_schema`。
- 四服务联动：微服务冒烟 **21 项 OK（skipped=3）**、网关冒烟 **13/13 OK**。

**限制**：`stamp head` 只保证版本号对得上，**不比对列差异**；如果旧库存过手工改动，需要自己跑一次 `alembic check` 确认。
另外 document / llm / notification / auth / workflow 的启动仍是 `create_all`（它们自己的 `init_db` 未改），只有网关和 rag 走迁移。

### 2026-11-23 · 第 17 轮：MinIO 分支用 `moto` 真实验证（不再“未验证”）

**背景**：MinIO 直到第 12 轮都是「代码在、没跑过」：`docker pull minio/minio` registry 超时，
`quay.io` unauthorized，`docker.1ms.run` manifest unknown，`dl.min.io/.../minio.exe` 已 410 Gone。

**做法**：用 `moto` 起一个内存 S3 端点，把 document-service 切到 `STORAGE_PROVIDER=minio` 跑同一套冒烟。

```bash
python -m pip install "moto[server]"          # 仅本地验证用，未加入 requirements
python -m moto.server -p 9000 &
STORAGE_PROVIDER=minio MINIO_ENDPOINT=127.0.0.1:9000 \
MINIO_ACCESS_KEY=minioadmin MINIO_SECRET_KEY=minioadmin123 \
MINIO_BUCKET=documents MINIO_USE_SSL=false MINIO_REGION=us-east-1 \
DATABASE_URL="sqlite+aiosqlite:///./document_minio_test.db" \
  … -m uvicorn app.main:app --port 8004
```

**真实通过（不是只编译）**：

- 自动建桶：`bucket_exists("documents") = True`（启动时不连对象存储，首次读写才建桶，符合设计）。
- 直传 multipart：`PUT /documents/<tenant>/<xx>/<hash>.txt` 200，对象能在桶里列出、大小对得上。
- 预签名上传：moto 收到带 `X-Amz-Algorithm/X-Amz-Credential/X-Amz-Signature` 的 PUT 并返回 200；
  预签名下载同等有效（否则 `complete` / download 用例会挂）。
- `complete` 后自动解析 + RAG 入库、`/process` 与流式上传/下载字节一致均通过。
- 微服务冒烟 **21 项 OK（skipped=3）**、网关冒烟 **13/13 OK**，与 local 模式结果一致。

**限制**：moto 是 S3 协议的内存实现，不验证 MinIO 特有的行为（桶策略、分布式、版本控制、
服务端加密、分片上传的并发与重试）。真实 MinIO 仍需在有网络的机器上跑一次；但至此
`MinioClient` 的桶创建 / put / get / remove / presigned 已被真实请求覆盖。

### 2026-11-23 · 第 16 轮：写下服务拆分现状（`docs/architecture/service-split.md`）

将「哪些资源能拆、哪些不拆、为什么」固化成一张可审查的矩阵，避免下一轮重新推一遍：

- **判定标准**：数据归属单一 + 契约可无损映射 + 身份/权限能传导，三条缺一不拆。
- **矩阵**：9 个服务端口与存储；15 类资源分别标注 ✅ 已拆 / 🟡 可拆未接 / ❌ 不拆。
- **已拆两组**的适配点与降级（`search/type` 过滤忽略、`/chunks` 与 `unpublish` 501、KB 统计走内部接口）。
- **未接三组的具体卡点**：notification 的 `int` 主键 + `subject/content` vs UUID + `title/data`；
  llm 的「模型目录」与「模型网关」不是一回事；rag 与网关各自一套知识库、ID 不互通。
- **开关组合矩阵**：四种组合下文档写在哪、KB 计数从哪来、哪些能力降级。
- **拆分态最小路径**：定归属 → 迁数据 → 网关变聚合 → 前端改数据源 → 双写观察，估 1–2 周。

本轮只改文档，未改代码；验证入口与用例名在文档 §8 与 `runbooks/local-dev.md` 中互相引用。

### 2026-11-23 · 第 15 轮：转发模式下知识库统计不再失真（+ 软删除重传）

**问题**：`GATEWAY_PROXY_DOCUMENTS=true` 时文档写进 document-service 的库，网关知识库页的
`document_count` / `chunk_count` / `recent_documents` 仍读网关本地 `documents` 表 → 永远是 0 / 空列表。

- document-service 新增内部接口 `POST /api/v1/internal/kb-stats`（新路由 `internal_router`，在 `main.py` 注册）：
  按租户批量返回每个 KB 的 `document_count / chunk_count / token_count / documents_by_status / recent_documents`。
  最近 5 篇用一次 `ORDER BY created_at DESC LIMIT 5*N` 再在 Python 里截断，避免 N+1。
- 网关 `knowledge_bases.py` 新增 `_proxied_kb_stats()`：转发开关打开时用 `internal_headers` 签名调用该接口（5s 超时）；
  **失败只记 warning 并回退网关本地计数**，不让微服务抖动带崩知识库页。列表 / 详情 / `/{id}/stats` 三处都用它覆盖统计。

**顺带修了两个上传去重的真 bug**（第 13 轮 documents 转发 ERROR 的根因）：

- `documents` 上有 `(tenant_id, file_hash)` 唯一约束，**软删除的行同样占着它**。
  之前「删了再传同一份内容」既不能插入（撞约束 500），也不能把 DELETED 当重复返回
  （它的存储对象已经被删，后续 process/download 报「对象不存在」）。
- 新增 `_revive_deleted_document()`：create / multipart / complete 三条链路遇到 DELETED 记录时
  **复用同一条记录（ID 不变）**，清空 `chunk_count / token_count / page_count / error_message / processed_at`，
  状态回到 `UPLOADING`（登记）或 `UPLOADED`（文件已落盘），让调用方重新解析/入库。

**验证**：新增 `test_kb_stats_follow_proxied_documents`：建 KB → 统计 0 → 网关建文档 → 统计 1 且列表/详情同步 →
删除后同 hash 重建断言 ID 不变。微服务冒烟 **21 项 OK（skipped=3）**，网关冒烟 **13/13 OK**。

### 2026-11-23 · 第 14 轮：转发路径补回网关 RBAC

背景：第 10–13 轮的转发只验 JWT，等于**任何登录用户都能删文档、发布工作流**，是实实在在的安全回退。

- `proxy.py` 新增 `_require_permission()` / `_document_permission()`：
  GET → `document:read`；POST → `document:create`（`/reprocess` → `document:update`）；PATCH/PUT → `document:update`；
  DELETE → `document:delete`；上传/下载两个独立路由分别要求 create / read。
- `proxy_workflows.py` 新增 `_workflow_permission()`：GET → `workflow:read`；POST → `workflow:create`；
  PATCH → `workflow:update`；DELETE → `workflow:delete`；`/publish` → `workflow:update`；`/execute` → `workflow:execute`；
  `validate` 保持不限（与网关自带路由一致）。
- 权限表与网关原路由**同源**（`get_role_permissions` + `has_permission`），失败走原有 `HTTPException(403)`，
  前端错误处理不用改。
- 新增 `test_proxy_enforces_gateway_rbac`：管理员建一个 VIEWER → 该用户 GET 文档 200、
  POST 文档 403（`document:create`）、DELETE 文档 403（`document:delete`）、POST 工作流 403（`workflow:create`），
  最后清理测试用户。

**验证**：微服务冒烟 **20 项 OK（skipped=3）**；网关冒烟 **13/13 OK**（两个转发开关同时开启）。

### 2026-11-23 · 第 13 轮：workflow-service 接入网关转发（图结构双向转换）

**一、网关 → workflow-service 转发**

- 新增 `app/api/v1/proxy_workflows.py`（对应开关 `GATEWAY_PROXY_WORKFLOWS`，默认关），
  同样在 `main.py` 里注册在自带的 workflows 路由**之前**。
- 覆盖：列表 / 创建 / 详情 / PATCH / 删除 / `validate` / `publish` / `execute` / `executions`；
  `/workflows/{id}/unpublish` 微服务没有此接口 → **501 + 可读说明**。
- 两边的「图」结构不同，在 `proxy_adapters.py` 里做**双向转换**：
  - 节点：网关 `{id, type 大写, name, position, config, inputs[{id,...}]}` ↔ 微服务 `{id, type 小写, position, config, inputs[str]}`；
    `name` 在微服务侧存进 `config.name`，回读时还原。
  - 边：网关 `{source_node_id, source_port_id, target_node_id, target_port_id}` ↔ 微服务 `{source, target, source_handle, target_handle}`。
  - 列表分页 `page/page_size → skip/limit`，状态筛选小写化，用 `X-Total-Count` 拼分页信封。
  - 执行请求 `{input | input_data}` → `{input_data, async_mode}`；执行结果字段映射（节点级日志在 `/executions/{id}/logs`，未拉取）。

**二、workflow-service 修的三个真实 bug**

1. **`/workflows/validate` 必 500**：环检测写成 `for node_id in nodes:`，把 `NodeDefinition` 对象当 key 丢进 set →
   `TypeError: unhashable type`。旧冒烟传的是空图（`{"definition": …}` 实际被当成空定义），所以一直没暴露。
   改为遍历 `adj` 的节点 id，并有注释说明。
2. **按 id 的接口不校验租户**：get / update / delete / publish / execute 都用 `session.get`，
   知道 UUID 就能跨租户操作 → 新增 `_get_tenant_workflow()`（id + 租户一起查），执行记录详情也加了租户过滤。
3. **列表没有总数**：`/workflows` 与 `/executions` 加 `X-Total-Count` 响应头（列表体仍是数组）。

**验证**

- 微服务冒烟：**19 项 OK（skipped=3）**。新增 `test_gateway_forwards_workflows`：网关登录 → 列表（信封+分页头）→
  创建（定义双向转换、`status=DRAFT`）→ `validate`（`valid=true`）→ 详情 → `publish`（`PUBLISHED`）→ `unpublish` 断言 **501**；
  `test_workflow_create_and_validate` 新增「另一租户按 id 取 → 404」。
- 网关冒烟：**13/13 OK**（`GATEWAY_PROXY_DOCUMENTS` + `GATEWAY_PROXY_WORKFLOWS` 同时开启）。

**未接的三个服务（原因不是「没写适配器」，而是契约/数据归属要先决定）**

- **notification-service**：主键是 `int`，字段是 `recipient_id / subject / content / status`；网关是 `UUID` +
  `user_id / title / type / data / read`。无法无损互转（假 UUID 会让后续读/删对不上）。
- **llm-service**：网关只对外暴露 `/models`（自己维护的模型目录），微服务是 `/providers` + `/models` + `/chat`，
  语义不同，直接转发会让管理后台的模型页变空且字段对不上。
- **rag-service**：知识库 ID 与网关的不是同一套（两套库），且网关 KB 响应里的 `document_count / chunk_count` 是网关侧统计，
  rag 没有这些聚合。要先决定「知识库到底归属哪个服务」，再谈转发。

**限制**：转发路径的权限按方法/路径映射回网关原有权限表（第 14 轮已补，见上）；
但**资源级归属**仍依赖微服务自己的租户校验，网关不再重复检查「这个文档是不是你的」。

### 2026-11-23 · 第 12 轮：转发改流式（去掉全量缓冲）+ 工作台页面级验证

**一、网关转发不再把大文件读进内存**

- 新增 `_forward_generic()` 的流式实现：请求体用 `request.stream()` 直接交给 httpx，
  响应体用 `StreamingResponse` + `aiter_bytes()` 逐块下发，`finally` 里关闭上游响应与 client。
  只有 JSON（小体积）和错误体仍会读完再包信封。
- `/documents/upload` 的 multipart 请求体也改成流式转发（响应仍是小 JSON，读完拿 `id` 再补一次 `/process`）。
- 补上一个漏掉的路径映射：网关的 `GET /documents/{id}/download` → 微服务 `/download/{id}`，字节流式返回。
  之前这个 URL（正是上传响应里 `url` 字段）在转发模式下会 404。

**二、工作台页面级验证（3002 + 网关转发开）**

- 启 3002 + 网关（`GATEWAY_PROXY_DOCUMENTS=true`）+ document-service，在浏览器里真实登录（`admin@example.com`）→
  知识库 → 文档页：列表请求 `GET /api/v1/documents?knowledge_base_id=…&page=1&page_size=100` **200**，
  页面正常渲染「暂无文档」，无 console 报错。
- 在「添加文档」弹窗里填表创建 → `POST /api/v1/documents` **201**（经网关转发），
  列表刷新后能读到刚建的文档（字段名、分页、信封都正确），随后通过网关 DELETE 清理。
- 备注：预览标签页处于后台（`document.visibilityState=hidden`），CSS 动画被浏览器暂停，
  Radix Dialog 等不到 `animationend` 所以看起来没关闭——这不是产品缺陷；没在可见窗口里复看一眼关闭动作。

**验证**

- 微服务冒烟：**18 项 OK（skipped=4）**。网关转发用例现在上传约 **700KB** 正文再经
  `/documents/{id}/download` 下回来做**字节相等**断言，覆盖流式上传 + 流式下载。
- 网关冒烟：**13/13 OK**（转发开启）。

**MinIO：仍然阻塞（本轮又试了 4 种途径）**

- `docker pull minio/minio`：`registry-1.docker.io` 连接超时；
- `quay.io/minio/minio`：`unauthorized`；`docker.1ms.run/minio/minio`：manifest unknown；
- 官方 Windows 二进制 `https://dl.min.io/server/minio/release/windows-amd64/minio.exe`：**410 Gone**。
- 结论：本机拿不到 MinIO 二进制/镜像，`STORAGE_PROVIDER=minio` 分支仍**未验证**（本地开发继续用 `local`）。

**未做**：llm / workflow / notification / rag 四组接口还没接入网关转发（每组契约都不同，需要单独适配）。

### 2026-11-23 · 第 11 轮：转发契约对齐 + document-service 租户校验

**一、转发响应回到网关契约（前端不用改接口层）**

- 新增 `app/api/v1/proxy_adapters.py`（纯数据转换）：微服务的裸对象 → 网关的
  `{success, data}` 信封 + `file_name` / `mime_type` / `type` 等字段名。
- 列表：网关的 `page/page_size` → 微服务的 `skip/limit`，`status` → `status_filter`；
  document-service 的列表新增 **`X-Total-Count`** 响应头（列表体仍是数组，老调用方不受影响），网关用它拼
  `{items,total,page,page_size,total_pages}`。
- 创建：网关 `DocumentCreate`（title/type/file_name/mime_type/metadata.file_hash）→ 微服务字段；
  缺 `file_hash` 时生成一个，避免微服务 422。
- 上传：网关的 `/documents/upload` → 微服务 `/upload/multipart`，并**补调一次 `/process`**，
  保持网关「上传即解析」的行为；响应转成 `FileUploadResponse`（file_id/file_name/…）。
- 详情 / PATCH / DELETE / `reprocess`→`process` 均已映射；DELETE 把微服务的 204 转回网关的
  200 + 信封（前端读 `res.data`）。未适配的路径统一包信封，错误也转成网关错误格式。
- 明确降级：`/documents/{id}/chunks` 在 document-service 没有对应接口（分块在网关库或 rag）→ **501** + 可读说明；
  列表的 `search` / `type` 过滤微服务不支持，转发模式下忽略。

**二、修两个 document-service 的真实 bug**

1. **软删除后又出现在列表里**：`delete_document` 只把 `status` 改成 `DELETED`，而列表/计数不过滤，
   删除后刷新列表文档又回来了 → 列表与计数都加上 `status != DELETED`。
2. **按 id 的接口不校验租户**：`get / update / delete / versions / process / download` 都用
   `session.get(Document, doc_id)`，只要猜到别人的 UUID 就能跨租户读、删、下载、重新解析。
   新增 `_get_tenant_document()`（`id` + `current_tenant_id()` 一起查，找不到就 404），六处全部改用它。

**验证**

- 微服务：**18 项 OK（skipped=4）**。网关转发用例扩到断言：信封 + 分页字段、
  `file_name/type/mime_type` 字段映射、`/documents/upload` 经网关落到微服务、删除后不再出现在列表。
  `test_document_register_and_stats` 新增「另一租户按 id 取 → 404」。
- 网关：**13/13 OK**（转发开关开启时跑）。
- 手工：`GET /api/v1/documents?page=1&page_size=2` 经网关返回
  `{"success":true,"data":{"items":[],"total":0,"page":1,"page_size":2,"total_pages":0},...}`，
  响应头带 `x-gateway-proxy: document-service`。

**未验证**：没有起 3002 在浏览器里点文档页（只验证到 HTTP 契约层）；转发仍是全量缓冲（无流式/背压）；
`search`/`type` 过滤与 `/chunks` 在转发模式下不可用；MinIO 模式仍未验。

### 2026-11-23 · 第 10 轮：网关 → 微服务转发试点（document-service）

**目标**：`internal_headers()` 从第 6 轮就写好了，但一直没有调用方——网关和微服务之间没有真正的调用链路。
这轮把「网关鉴权 → 签名 → 转发」这段接上，先用风险最低的 document-service 试点。

**做了什么**

- 新增 `services/api-gateway/app/api/v1/proxy.py`：把 `/api/v1/documents`、`/api/v1/upload`、`/api/v1/download`
  三组路径转发到 `DOCUMENT_SERVICE_URL`。
  - 网关先用 `get_current_user` 解析 JWT（不复用客户端的信任头），再用 `internal_headers()`
    生成 HMAC 签名并注入 `X-Tenant-Id` / `X-User-Id`，微服务那侧的签名中间件照常验签。
  - `Authorization` 不透传给微服务（它不认 JWT，只认身份头+签名）；逐跳头与 `content-length` 被剔除，
    查询参数、请求体（含 multipart）、状态码、`content-type` / `content-disposition` 原样保留。
  - 上游不可达返回 **502**；`SERVICE_API_KEY` 未配置时返回 **503 + 可读文案**（而不是静默转成无签名请求）。
- 开关 `GATEWAY_PROXY_DOCUMENTS`（默认 `false`）：开启后在 `main.py` 注册，且必须放在网关自带的
  documents 路由**之前**，否则永远匹配不到。默认关闭是因为两条契约还没对齐（见下方「未验证」）。
- 顺手修两个从来没被调用过、所以一直没人发现的错默认值：
  `RAG_SERVICE_URL` 8002 → **8001**、`AUTH_SERVICE_URL` 8001 → **8007**（与 AGENTS.md 端口表一致）。

**验证**

- 网关 `GATEWAY_PROXY_DOCUMENTS=false`（基线）：`test_gateway_smoke.py` **13/13 OK**。
- 网关 `GATEWAY_PROXY_DOCUMENTS=true SERVICE_API_KEY=dev-internal-key` + document-service 8004：
  网关冒烟仍 **13/13 OK**（证明多注册一组路由不破坏原有接口）；
  微服务冒烟 **18 项 OK（skipped=4）**，新增用例 `test_gateway_forwards_documents_with_jwt_identity`：
  网关登录拿 JWT → 从 JWT 取租户 → 经网关 POST 文档 → 断言返回的 `tenant_id` 等于 JWT 租户 →
  同一个租户**直连 8004** 也能查到该文档（证明请求确实落在微服务，而不是网关自己的库）。
- 未开转发时该用例自动 skip（检测到网关自己的 `{success,data}` 信封），不会假绿。

**未验证 / 限制**

- 网关转发出去的是微服务的**裸 JSON**，而不是前端一直在用的 `{success, data}` 信封；字段名也不同
  （如 `filename` vs 网关的文档模型）。所以开关默认关闭，前端切换前必须先做契约对齐（已入 Backlog）。
- 只试点了 document-service；auth/llm/workflow/notification/rag 尚未接入转发。
- 微服务的 `/api/v1/storage/*`（local 预设上传）不建议经网关转发：那是给浏览器直传的能力型 URL。

### 2026-11-23 · 第 9 轮：预签名上传也自动解析入库 + 修 local 存储 401 回归

**一、补上第 8 轮遗留：`/upload/complete` 之后自动解析并入库**

- 新增配置 `AUTO_PROCESS_ON_UPLOAD`（document-service，默认 `true`）：预签名上传在 `/upload/complete`
  建好文档记录后**立即解析**，解析成功再走原有的自动入库（`AUTO_INGEST_TO_RAG`）。
  之前这条链路到「建记录」就结束了，`AUTO_INGEST_TO_RAG` 对它完全不生效。
- 把「解析 + 送 rag」抽成 `document.py#_parse_and_ingest()`，`/documents/{id}/process` 与 `/upload/complete` 共用，
  避免两条上传链路行为漂移。
- `/upload/complete` 响应新增 `document_status` / `processed` / `rag_ingested`（解析成功时还有 `page_count`）；
  解析失败**不让上传失败**：文档保留并标记 FAILED，响应里给 `process_error`，调用方仍拿到 `document_id`。

**二、修一个真实回归：local 模式的预签名上传被服务间签名挡成 401**

- 现象：`STORAGE_PROVIDER=local` 时 presigned URL 指向本服务自己的 `/api/v1/storage/{key}`，
  但第 6 轮的服务间签名把 `/api/v1/*` 全保护了，浏览器 PUT 文件直接 **401**。
- 为什么一直没发现：旧的冒烟用例在 PUT 处 `skipTest`（当时误报成「MinIO 下载 401」），被跳过掩盖；
  第 8 轮的自动入库用例走 multipart，没经过预签名路径。
- 修法：document-service 的 `EXEMPT_PREFIXES` 增加 `/api/v1/storage`。理由与 MinIO 预签名一致——
  这是「持有链接即可读写」的能力型 URL，调用方是浏览器/客户端，不可能带服务间签名。
- 同时修测试：`/upload/complete` 和 `/download/{doc_id}` 也要带签名，否则配置 `SERVICE_API_KEY` 后必 401。

**验证**

- `tests/test_microservices_smoke.py` 新增 `test_presigned_complete_auto_processes_and_ingests`：
  建知识库 → 预签名 → PUT → complete（带 `knowledge_base_id`）→ 断言 `processed/document_status/rag_ingested` →
  直接检索命中刚上传正文。
- 结果：**Ran 17 tests, OK (skipped=4)**（auth/llm/workflow/notification 未启动）；
  rag + document 全 UP 时 13 项真实通过，包含预签名自动解析入库与旧的「上传→下载→解析」用例（现在真的跑起来了）。

**未验证**：MinIO 模式仍未实测（镜像未缓存）；预签名链路的解析仍是同步的，大文件会拉长 complete 的响应时间（异步队列见 Backlog）。

### 2026-11-23 · 第 8 轮：上传即入库（P1）+ rag 错误映射与 BM25（P2）

**一、P1：document-service 解析完自动入库到 rag（不再手工建 rag 文档）**

- rag-service 新增 **`POST /api/v1/documents/ingest`**（`IngestRequest/IngestResponse`）：
  一次完成「按 `file_hash` 登记文档 → 用 `metadata.text` 分块 → 嵌入 → 刷新 BM25」，并返回
  `document_id / chunks_created / reused_existing`。同一租户下正文未变的重复上传**复用**文档，不会重复嵌入。
- document-service 新增 `app/services/rag_ingest.py`：`ingest_document_text()` 带 `X-Tenant-Id` / `X-User-Id`
  和**第 6 轮的 HMAC 签名**调用上面的接口；配置项 `RAG_SERVICE_URL`（默认 `http://127.0.0.1:8001`）、
  `AUTO_INGEST_TO_RAG`（默认 true）。没有知识库归属或正文为空时跳过。
- `/documents/{id}/process` 解析成功后调用它，响应新增 `rag_ingested` 字段；调用是 **best-effort**：
  rag 没起 / 签名不符 / 知识库不存在只记 warning 并返回 `false`，**不会让上传失败**。
- 实测：`/upload/multipart`（带 `knowledge_base_id`）→ `/process` 返回 `rag_ingested: true` →
  `/retrieval/search` 直接命中刚上传的那段正文（`total_found=1`、`degraded=false`）。

**二、P2-a：embedding 不可用从「静默空结果 / 500」改为 503 + 可读文案**

- 新增 `app/core/errors.py#EmbeddingUnavailable`（含 `public_message()`：
  「Embedding 服务不可用（模型 X）：<原因>。请检查 EMBEDDING_API_BASE / EMBEDDING_API_KEY 是否可用」）。
- `retrieval._embed_query` 以前 `except Exception: return None` → 检索 200 但 0 结果；现在抛 `EmbeddingUnavailable`。
- `document_processor._embed_chunks` 把底层 `openai` 异常包装成 `EmbeddingUnavailable`。
- `/documents/{id}/process`、`/embeddings`、`/documents/ingest` 统一映射 **503**；
  `/retrieval/search` 更细致：先行尝试向量，失败则降级为 **BM25-only**，响应带 `degraded` + `degraded_reason`；
  只有「降级且关键词也没命中」才返回 503，避免把有结果的搜索打死。
- 实测：不存在的模型 → `/embeddings` 与 `/ingest` 均 503 且文案含检查项；embedding 地址指错时，
  同一知识库检索返回 200 + `degraded: true` + BM25 命中。

**三、P2-b：BM25 分支真正生效（原来三处都是死的）**

1. `process_document` 里的 `_update_bm25_index` 调用被注释、函数体是 `pass` → 实现为「按知识库从 DB 读全部分块重建」；
   并改为**模块级共享缓存** `get_bm25_indexer(kb_id)`，入库重建后检索侧立刻生效。
2. 冷启动没有索引 → `retrieval._bm25_search` 在 `bm25 is None` 时从 DB **懒构建**（不必等下一次入库）。
3. 分词 `re.findall(r"\w+")` 对中文等于整段一个 token，查询永远不重叠 → 改为「英文/数字按词 + 中文单字 + 相邻二字」。
4. 打分器 `BM25Okapi` 在**单文档知识库**上 IDF 为负（`eps * average_idf`），分数全负被 `score > 0` 过滤掉 →
   换 `BM25Plus`（IDF 恒正）。索引文件名加 `_v3.pkl` 后缀，旧索引自动失效重建。
5. 空语料 `BM25Okapi([])` 会抛异常 → `build/_load` 均加了空语料保护。

**验证**

- `tests/test_microservices_smoke.py` 新增 3 项：`test_rag_ingest_is_one_step_and_idempotent`、
  `test_rag_embedding_failure_is_503_with_readable_reason`、`test_document_parse_auto_ingests_to_rag`
  （doc-service → rag 自动串联 + 检索命中）；新增 multipart 上传辅助 `call_multipart()`。
- 结果：**Ran 16 tests, OK (skipped=5)**，其中 rag/document 全 UP 的 11 项真实通过；
  跳过的是 auth/llm/workflow/notification（本轮未启动）与 MinIO 预签名下载（镜像未缓存）。
- 另用真实 upload→process→search 脚本与「embedding 故意指错」的第二个实例（8002）分别验证了
  自动入库命中、503 映射、BM25 降级命中。

**未验证**：网关 → 微服务的转发链路仍未接（P1 走的是 document→rag 直连签名）；
`AUTO_INGEST_TO_RAG` 只覆盖 `/process`，预签名 `complete` 后的自动解析链路未接；MinIO 模式仍未验证。

### 2026-11-23 · 第 7 轮：前端请求层/鉴权单测 + 登录 E2E + 修「未登录永远转圈」

**一、前端单测从 24 → 41（测真实现，不测替身）**

- `tests/unit/setup.tsx` 全局 mock 了 `@/lib/api` 和 `@/lib/auth`（组件测试需要），所以新用例必须
  `vi.unmock` 才能测到真实实现——否则又是第 5 轮那种「测了个假函数」。
- 新增 `tests/unit/api-client.test.ts`（10 项）：用一个可编程 axios 替身（**真的会执行 api.ts 注册的拦截器**），
  覆盖 Bearer 注入 / 无 token 不发头 / 网关信封解包 / 裸响应直通 / `skip+limit → page+page_size` /
  401 刷新后重放 / 并发 401 只刷新一次（`refreshPromise` 去重）/ 刷新失败清 token 回首页 / 无 refresh_token 不刷新 /
  `getDocuments` 字段映射。
- 新增 `tests/unit/auth-provider.test.tsx`（7 项）：测真实 `AuthProvider`——无 token 不请求 `/auth/me`、
  有 token 带 Bearer 拉用户并解包 tenant、`/auth/me` 失败后刷新再取、刷新失败清 token、
  登录成功存双 token 并 `router.push('/')`、登录失败抛后端 detail、登出清空身份。

**二、修一个真实 UX bug（E2E 发现的）**

- `app/workflows/page.tsx`：`loading` 初始为 `true`，只有登录后 `loadWorkflows()` 才会置 `false`。
  **未登录直接访问 `/workflows` 会永远停在「加载中，请稍候...」**，连「请先登录」提示都看不到。
  修法：`useEffect` 里先等 `authLoading` 结束，未登录时 `setLoading(false)` 再返回。
- `app/knowledge-bases/page.tsx` 同一模式、同一个坑，一并修掉。
- 回归用例：E2E 里断言未登录访问 `/workflows` 显示「请先登录」且「加载中」不可见。

**三、E2E 从「一次都没跑通」变成 7/7 绿**

- 两条 spec 原本是对着想象中的 UI 写的：`baseURL` 指 3000（实际 3002）、`/login` 路由（实际登录表单在首页 `/`）、
  假账号 `admin@test.com/password123`（实际 `admin@example.com/admin123`）、编辑器内部组件名的猜测性断言。
- `playwright.config.ts`：`baseURL` 改 3002、`webServer` 用 `pnpm dev`、默认只跑 chromium（firefox/webkit 按需 `--project=`）。
- `tests/e2e/auth.spec.ts` 重写（3 项）：表单渲染 / 错误密码不进门 / 正确账号登录后出现「知识库」标签且 token 落库。
- `tests/e2e/workflow-editor.spec.ts` 重写（4 项）：未登录提示先登录（回归）/ 列表加载 / 新建对话框可开可取消 / 搜索框过滤；
  登录态用真实网关 `/auth/login` 拿 token 后 `addInitScript` 注入 localStorage；网关未启动时自动 skip。
- Playwright 浏览器版本与已缓存版本不一致，补了 `playwright install chromium`。

**验证**：`vitest run` **41/41**；`tsc --noEmit` 干净；`playwright test` **7/7 通过**（真实登录网关 8000）。

**未验证**：firefox / webkit 两个 project 未跑；管理后台 `apps/admin` 仍无单测；E2E 依赖本地网关
（CI 需要先起 8000，否则 3 项后端用例会 skip）。

### 2026-11-23 · 第 6 轮：服务间签名（P0 身份信任边界）

**问题**：微服务无条件信任 `X-Tenant-Id` / `X-User-Id`，任何能直连 8003–8007 的人都能冒充任意租户读写数据。

**做了什么**

- 新增 `app/core/service_auth.py`（6 个服务各一份，内容一致）：`ServiceAuthMiddleware` 纯 ASGI 中间件，
  校验 `X-Service-Timestamp` + `X-Service-Signature`；签名 = `HMAC-SHA256(SERVICE_API_KEY, "METHOD
PATH
tenant
user
timestamp")`，
  时差窗口 **300 秒**，`hmac.compare_digest` 比较；缺失 / 过期 / 不匹配分别返回可读的中文 401 文案。
- 中间件注册在 `TenantContextMiddleware` **外层**（先验签、再解析租户）；
  `/health`、`/ready`、`/metrics`、`/docs`、`/redoc`、`/openapi.json` 豁免（探针与文档不能被签名挡住）。
- `SERVICE_API_KEY` 为空 = **本地开发模式**（不校验）；一旦配置就对所有 `/api/v1/*` 强制验签。
  auth / notification / llm 三个服务的 `config.py` 补了该字段（document / rag / workflow 原本已有）。
- 网关侧新增 `app/core/internal_auth.py#internal_headers()`：转发给微服务时生成同样的头，
  未配置密钥时**显式抛错**而不是静默不签名（否则会线上静默降级成无签名调用）。
- `start-microservices.ps1` 为 5 个服务注入 `SERVICE_API_KEY=dev-internal-key`；根 `.env` / `.env.example` 补同名变量（含注释）。
- 冒烟测试：`call()` 默认自动签名，新增 3 个用例（6 个服务逐一断言）——**未签名 401 / 错误密钥 401 / 过期签名 401**；
  通过 `sign=False`、`sign_key=…`、`sign_ts=…` 构造坏请求。旧的不签名调用现在会直接 401，这一点写进了 runbook。

**验证**：网关 **13/13 OK**；微服务 **Ran 13 tests, OK (skipped=3)**，5 个服务全 UP。

**未验证**：rag-service（需要 PostgreSQL + pgvector，本机未起 Docker）；网关真正转发到微服务的链路还没接
（网关目前仍是单体，`internal_headers()` 已就绪但暂无调用方）。

**残留**：不配置 `SERVICE_API_KEY` 时仍是 dev 模式；生产必须两侧配置同一密钥（见 Backlog）。

### 2026-11-22 · 第 5 轮：RAG 检索全链路 + 文档上传链路 + 前端测试转绿

**一、RAG 真正端到端跑通（本地 Ollama `embeddinggemma:300m`，768 维）**

- `DocumentChunk.embedding` 不再写死 `Vector(1536)`，改为 `Vector(settings.EMBEDDING_DIM)`：
  换模型只需改环境变量（`EMBEDDING_DIM=768`），不用改代码/手写迁移。
- `process_document` 的 `_extract_text` 不再是纯占位：优先用 `metadata.text`（上游解析结果），
  没有正文时才退化为占位文本并在注释里写清限制。
- `DocumentCreate` 新增 `metadata`（ORM `meta`）字段，登记文档时可直接带正文。
- 检索查询向量改用 **知识库自己的 `embedding_model`**（之前用全局默认，KB 换模型会导致维度不匹配）。
- 修 `NameError: DocumentStatus is not defined`（processor 漏导入）——`/documents/{id}/process` 之前必 500。
- 重复 `file_hash` 从 500 改为 **409**（漏出的 `IntegrityError`）。
- `/documents/{id}/process` 的 body 改为可选（路径里已有 doc id）。
- 实测：3 块入库，`出差住酒店能报销多少` 命中差旅报销段，`年假有几天` 命中假期制度段。

**二、document-service 真正可上传（新增本地存储后端）**

- 新增 `app/services/storage.py`：`MinIOClient` 下沉至此，新增 `LocalStorageClient` 与 `get_storage_client()`；
  `.env.example` 里写了很久的 `STORAGE_PROVIDER=local` 现在**真的生效**（零依赖本地开发）。
- local 模式的 presigned URL 指向本服务 `PUT/GET /api/v1/storage/{object_key}`，与 MinIO 预签名用法一致，
  `object_key_from_path()` 统一 `s3://` / `local://` 两种存储路径。
- 修 3 个把上传路径卡死的真实 bug：
  1. `complete_upload` / `upload_multipart` 调用不存在的 `DocumentProcessor.detect_type()`（应走 `infer_document_type`）——预签名上传完成必 500；
  2. `storage_path` 写死 `s3://{bucket}/…`，local 模式下下载会拼错；改由 `storage.describe_path()` 生成；
  3. `doc.meta.update(...)` 原地修改 JSON 列不会被 SQLAlchemy 标记为脏数据 → 解析结果丢；改为整体赋值。
- 解析出的正文写入 `metadata.text`，下游 RAG 可直接复用，避免二次解析文件。
- `/documents/{id}/process` body 改为可选；实测：预签名 → PUT → complete → 下载字节完全一致 → 解析成功（page_count=1）。

**三、前端测试从 9 红转 24 绿**

- 根因：`tests/unit/setup.tsx` 把 `@/lib/utils` 整体 mock 成假实现，`utils.test.ts` 测的是假函数；
  同时 `workflow-validation.test.ts` 里复制了一份校验逻辑，和产品代码无关。
- 新增 `lib/workflow-validation.ts`（纯函数导出 `validateWorkflow`），`workflow-editor.tsx` 在调用后端前先本地校验；
  单测改为引用真实实现（13 项）。
- 修 `lib/utils.ts` 两处偏离契约的实现：`formatNumber` 缺 `B` 后缀；`truncate` 把 `length` 当截断长度而不是结果总长度。
- 结果：`vitest run` **24/24 通过**，`tsc --noEmit` 干净。

**四、配套**

- `start-microservices.ps1` 里 document-service 默认带 `STORAGE_PROVIDER=local` + 本地目录 + `PUBLIC_BASE_URL`。
- `.env.example` 补上 `EMBEDDING_API_KEY / EMBEDDING_API_BASE / EMBEDDING_MODEL / EMBEDDING_DIM`（含 Ollama 注释）。
- 冒烟测试扩到 **10 项**：新增 RAG 分块→嵌入→检索、document 预签名上传→下载→解析。
- 注意：为了让向量列变成 768 维，**重建了本地开发库的三张表**（只有冒烟数据，无真实业务数据）。

### 2026-11-22 · 第 4 轮：rag-service 跑通（真实 PostgreSQL + pgvector）

- 启动 Docker Desktop（WSL2 已就绪，18 秒内可用），`docker compose up -d postgres redis`：
  **postgres healthy、vector 扩展就位（`infra/docker/postgres/init.sql` 已建）、三张表由 `create_all` 创建成功**。
- rag-service 以 `DATABASE_URL=postgresql+asyncpg://…@localhost:5432/enterprise_ai` 启动 8001：
  `/health` 200、`/ready` 200（真 ping 数据库）、`document_chunks / documents / knowledge_bases` 均落库。
- 冒烟测试扩展到 **8 项**，新增 rag 用例：建知识库 → 列表（租户隔离）→ 详情 → PATCH 描述 → 登记文档 → 按 `kb_id` 列文档。
- `docker-compose.yml` 删掉已弃用的 `version: '3.8'`（compose 每次都会警告）。
- 未完成：向量检索端到端（`/retrieval/search` 需要 `EMBEDDING_API_KEY`，本机 `.env` 为空）；
  MinIO 镜像拉取失败（Docker Hub 超时、daocloud 镜像源对 `minio/minio` 返回 denied），文档上传链路仍阻塞。

### 2026-11-22 · 第 3 轮：微服务真正可运行 + 请求上下文

**目标**：把「微服务只能 `import`、不能启动」变成「能启动、能读写、能验证」。

- 新增 `start-microservices.ps1` / `.cmd`：一键用 SQLite 启动 5 个服务，逐个等待 `/health`，端口已占用则跳过。
- 新增 `tests/test_microservices_smoke.py`（7 项）：真实注册/登录、通知写入与已读、Provider+Model 创建、文档登记与统计、工作流创建与校验，外加租户隔离、`/ready` 探活、非法租户头 400。
- 修掉 6 类真实 bug（在 PostgreSQL 上同样会出问题）：
  1. `JSONB` / `postgresql.UUID` 写死 → 改用可移植 `JSON` / `Uuid`（PG 上仍是原生 UUID）。
  2. `create_async_engine(pool_size=…)` 在 SQLite 非法 → 仅非 sqlite URL 才传池参数。
  3. `index=True` 与同名显式 `Index(...)` 重复 → `create_all` 报 `index … already exists`；删掉 26 处冗余索引。
  4. schema 字段叫 `metadata`、ORM 属性叫 `meta` → 读接口 500、写接口传错关键字；改为 `meta` + `AliasChoices("meta","metadata")` + `serialization_alias`（对外 JSON 仍是 `metadata`）。
  5. `document_type` / `storage_path` 非空但从未赋值 → 按 MIME/扩展名推导类型，存储键 `documents/{tenant}/{file_hash}`。
  6. `CostSummary.period_start/end` 必填 datetime 但服务返回 `None` → 改为可选。
- 新增 `app/core/context.py`（llm/document/workflow/rag 各一份）+ 纯 ASGI 中间件：
  31 处硬编码演示租户全部改为 `current_tenant_id()` / `current_user_id()`，
  通过 `X-Tenant-Id` / `X-User-Id` 请求头注入；不带头回退演示租户，头不是 UUID 直接 400。
- `/ready` 从「永远 ready」改为真 ping 一次数据库（`SELECT 1`），失败返回 503 并带原因；
  auth / notification / llm / document / workflow / rag 六个服务统一。

### 2026-11-22 · 第 2 轮：审计闭环 + 生产构建

- 新增 `services/api-gateway/app/services/audit.py`（`record_audit` / `jsonable`）。
- 审计接入：登录成功/失败/账号非 ACTIVE/登出、用户增改删（含 old→new）、模型启停、租户创建与重命名（新增 `PATCH /tenants/{id}`，仅 SUPER_ADMIN）。
- 后台审计页对齐真实字段（`resource` / `success` / `old_value` / `new_value` / `ip_address` / `error_message`），总览页同步。
- 移除后端并不存在的「删除租户」入口与 `deleteTenant`。
- `apps/admin`、`apps/web` 的 `next build` 均通过；构建会覆盖 `.next`，之后必须重启 dev server。
- 修复微服务导入问题：补 6 个依赖、`llm-service` 缺 `from uuid import UUID`、`document-service` 导入即连 MinIO（改为首次读写才建桶）。

### 2026-11-22 · 第 1 轮：后台五页 + 网关冒烟

- 管理后台五个页面 + 总览重写；`PATCH /api/v1/models/{id}`；`tests/test_gateway_smoke.py` 13 项冒烟；docs 三份；`start-dev.ps1` 纳入 admin。

---

## 4. 已验证的检查（改完必须重跑）

```bash
# 1) 网关冒烟：20 项（健康/认证/权限/审计/成本/校验 + 解析通知 2 项 + 工作流执行器 3 项
#          + AI 节点 2 项：LLM 真调用/成本、RAG 真检索）
python tests/test_gateway_smoke.py

# 2) 微服务冒烟：7 项（未启动的服务自动跳过）
python tests/test_microservices_smoke.py

# 3) 前端（根目录一条命令覆盖 lint / typecheck / 单测 / 构建，依赖先在根 pnpm install）
pnpm install --frozen-lockfile
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

最近一次结果（2026-11-26，第 30 轮）：`ruff check services tests` → 0；`pytest tests/test_gateway_smoke.py -q`
→ **20 passed**，两个冒烟文件 → **25 passed / 17 skipped**（Ollama 在跑，LLM 节点用例真实调用并断言 token 与成本记录）。
第 29 轮结果：`ruff check services tests` → 0；`pytest tests/test_gateway_smoke.py -q`
→ **18 passed**（新增工作流执行器 3 项），两个冒烟文件 → **23 passed / 17 skipped**；`apps/web tsc --noEmit` → 0。
第 28 轮结果：`ruff check services tests` → 0；默认模式
`pytest tests/test_gateway_smoke.py -q` → **15 passed**，两个冒烟文件 → **20 passed / 17 skipped**；
转发模式（notification-service + `GATEWAY_PROXY_NOTIFICATIONS=true`）下通知 2 项 → **2 passed**，
手工上传也确认通知真的落到了微服务；工作流转发模式 `-k gateway_forwards_workflows` → **1 passed**（含执行后通知断言）。
第 27 轮结果：`pnpm --filter @enterprise-ai/web` 的 `typecheck` / `lint` / `test`（**45 passed**）/ `build` 全部 exit 0，
构建产物里有 `○ /notifications`；网关（默认模式）+ `apps/web` `playwright test` → **9 passed**；
`pytest tests/test_microservices_smoke.py tests/test_gateway_smoke.py` → **18 passed / 17 skipped**
（默认模式未开转发、未设 `SERVICE_API_KEY`，转发相关 2 项跳过）。
第 26 轮结果：`ruff check services tests` → 0；notification-service 迁移
（临时库 2 行 + 真实库 18 行）全部保留数据、`alembic check` 无漂移；
`pytest tests/test_microservices_smoke.py -k "notification or ready"` → **3 passed**（含新增
`test_gateway_forwards_notifications`）；`pytest tests/test_gateway_smoke.py` → **13 passed**；
默认模式（开关关）通知接口仍是网关自己的实现。
第 25 轮结果：`pnpm install --frozen-lockfile` → 0；临时 git 仓库里
`changeset status` → exit 0（patch @enterprise-ai/admin）、`changeset version` → admin 0.1.0→0.1.1 +
CHANGELOG、无 changeset 时 `status` → exit 1（CI 已兜）；`ci.yml` `yaml.safe_load` 通过（`release` 6 步）。
第 24 轮结果：按 CI 的 `e2e-tests` job 命令实跑，
`apps/admin` `playwright test` → **8 passed**（20.9s）、`apps/web` `playwright test` → **7 passed**（19.8s），
网关 3s healthy、演示账号登录 200；`ci.yml` 用 `yaml.safe_load` 解析通过（11 个 job）。
第 23 轮结果：`pnpm lint` / `pnpm typecheck` / `pnpm test`（**75 passed**：web 41 + admin 34）/
`pnpm build` 全部 exit 0；`apps/admin` `vitest run` → **34 passed**。
第 22 轮结果（安装链路）：根 `pnpm install --frozen-lockfile` / `pnpm lint` / `pnpm typecheck` /
`pnpm test`（69 passed）/ `pnpm test:coverage`（产出 lcov）/ `pnpm build` 全部 exit 0；
两个 app 的 `dev server` 起得来且 `GET /` 200。第 21 轮结果：
`apps/admin` `vitest run` → **28 passed**（请求层 14 / utils 8 / AuthGate 6），`tsc --noEmit` 通过；
本地按 CI 命令起网关后 `pytest tests/test_gateway_smoke.py -q` → **13 passed**；`.github/workflows/ci.yml` YAML 解析通过。
第 20 轮的基线仍有效：
`ruff check services tests` 零告警；7 个服务全起后跑 `pytest tests/test_microservices_smoke.py tests/test_gateway_smoke.py`
→ **34 passed**（本轮前 4 个 embedding 相关用例因缺 key 报 500，修掉构造阶段的错误映射后转绿）；
5 个服务的「空库迁移 / 旧库 stamp」两条路径单独实测通过；`kubectl kustomize` 三个 overlay 各 34 个资源、exit 0；
`apps/admin` `tsc --noEmit` + `next build` 通过。
前端 `apps/web`（第 27 轮重跑）：**vitest 45/45 OK**、`tsc --noEmit` 干净、`playwright test` **9/9 OK**、`next build` 通过。

一条本地注意：本机 venv 里原本没装 pytest，`python -m pytest` 会直接报 `No module named pytest`，
已把 `pytest` 写进 `requirements-dev.txt`（`pip install -r requirements-dev.txt` 或 `pip install pytest`）。

---

## 5. 待办 Backlog

### ✅ 已完成 · P1 document-service 与 rag-service 自动串联（2026-11-23 第 8 轮）

- 采用「document-service 解析完成后回调 rag」路线：rag 新增 `POST /documents/ingest`，
  document-service 在 `/documents/{id}/process` 成功后带签名调用它（`RAG_SERVICE_URL` / `AUTO_INGEST_TO_RAG`）。
- 结果：上传 → 解析 → 自动入库 → 检索直接命中，无需手工建 rag 文档；响应里的 `rag_ingested` 可判断是否成功。
- ~~剩余：预签名 `complete` 未自动解析/入库~~ ✅ 第 9 轮已补齐（`AUTO_PROCESS_ON_UPLOAD`，响应 `processed` / `rag_ingested`）。
- 剩余：网关转发链路仍未接；解析是同步的，大文件会拉长上传完成接口的响应。

### ✅ 已完成 · P2 rag 错误映射与 BM25（2026-11-23 第 8 轮）

- embedding 不可用 → `/embeddings`、`/documents/{id}/process`、`/documents/ingest` **503 + 可读文案**；
  `/retrieval/search` 降级为 BM25-only 并在响应里给 `degraded` / `degraded_reason`（无命中才 503）。
- BM25：入库后重建 + 模块级共享缓存 + 冷启动懒构建；中文按字分词；`BM25Plus`；空语料保护。
- 剩余（P2）：BM25 索引仍按进程落盘共享目录，多副本部署需要换成集中式索引或每次全量重建。

### ✅ 已完成 · 用 `moto` 验证 MinIO 分支（2026-11-23 第 17 轮）

- 拿不到 minio 镜像时用 `moto` 内存 S3 端点替代，桶创建 / multipart put / presigned PUT+GET 全部实测通过，
  与 local 模式冒烟结果一致（复现步骤见 `docs/runbooks/local-dev.md`）。
- 剩余（可选）：真实 MinIO 集群的桶策略、分片上传、分布式行为仍需有网环境补一次。

### P1 · 网关按需路由到微服务（试点已完成，待契约对齐）

- ✅ 第 10 轮：document-service 的 `/documents`、`/upload`、`/download` 已可经网关转发
  （`GATEWAY_PROXY_DOCUMENTS=true`），网关负责 JWT 鉴权 + HMAC 签名 + 租户/用户注入。
- ✅ 第 11 轮：转发响应已包回 `{success, data}` 信封并映射字段（`proxy_adapters.py`），
  列表分页、创建、上传（含自动解析）、详情、删除、重解析均已对齐；`/chunks` 明确 501。
- ✅ 第 12 轮：工作台文档页已在 3002 真实登录验证（列表/创建经网关）；上传/下载改为流式，
  不再在网关内存里整块缓冲，并补上 `/documents/{id}/download` → `/download/{id}` 的映射。
- ✅ 第 13 轮：workflow-service 已接入（图结构双向转换、validate/publish/execute/executions），并修了
  validate 必 500、按 id 不校验租户、列表无总数三个真实 bug。
- ✅ 第 14 轮：转发路径已补回网关 RBAC（按方法/路径映射权限，VIEWER 写操作 403）。
- ✅ 第 16 轮：服务拆分现状与资源归属已固化为 `docs/architecture/service-split.md`（含未拆原因与拆分代价）。
- ✅ 第 17 轮：MinIO 分支已用 `moto` 真实跑通（桶创建 / put / get / presigned PUT+GET），不再列为未验证项；
  真实 MinIO 集群行为（桶策略、分片上传、分布式）仍需有网环境补验。
- ✅ 第 26 轮：notification 已接入（先把服务侧契约改成 UUID + `user_id/title/data/read`，再开
  `GATEWAY_PROXY_NOTIFICATIONS`），数据归属定为 notification-service。
- **剩余**：llm / rag 未接，原因见 `docs/architecture/service-split.md` §5.2 / §5.3
  （模型目录归属、两套知识库 ID 不互通）。
- **验收**：前端不改接口层就能在「网关 → 微服务」模式下跑通现有页面 + 冒烟。

### ✅ 已完成 · 工作流 AI 节点（2026-11-26 第 30 轮）

- 新增 `app/services/llm.py`（Ollama `/api/chat`）与 `app/services/retrieval.py`（本地关键词检索），
  对话与工作流共用；`conversations.py` 改为调用它们。
- 执行器新增 **LLM**（prompt 模板 + token 记成本）与 **RAG**（检索结果并进 `{{rag_context}}`）节点。
- 修掉 `/costs/summary` 一有成本记录就 500 的 bug（SQLite `func.date()` 返回字符串）。
- 剩余：只接 Ollama（OpenAI 未实现）；RAG 是关键词检索不是向量检索；金额记 0；条件分支仍走 workflow-service。

### ✅ 已完成 · 默认模式工作流执行器（2026-11-26 第 29 轮）

- `app/services/workflow_runner.py`：START / END / HTTP / DELAY 线性执行，变量 `{{name}}` 替换；
  其它节点类型预检直接失败并说明要用 workflow-service。
- 执行记录写 `output` / `error` / `completed_at` / `node_executions`（节点级明细），并复用 notify 发成功/失败通知。
- 前端执行按钮按真实状态提示，失败时弹出 `error`。
- 剩余：只支持 4 种节点；HTTP 节点没有 SSRF 防护；同步执行（HTTP 15s 超时、DELAY 10s 上限）；
  执行历史页还没展示节点明细。

### ✅ 已完成 · 通知由业务事件产生（2026-11-26 第 28 轮）

- 新增 `app/services/notify.py`：独立 session、失败只记日志、按开关写网关表或 POST 给 notification-service。
- 事件：文档上传解析完成/失败、重新解析、转发模式「上传即解析」、工作流执行结束（completed/failed/cancelled）。
- 测试：网关冒烟 +2（真实 multipart 上传 → 断言通知），工作流转发用例 +执行/通知断言；
  转发模式下也实跑过（通知写进 notification-service 后经网关读回）。
- 剩余：默认模式工作流没有执行器（无「执行结束」通知）；转发路径未逐条补通知；同步写入，量大要改队列。

### ✅ 已完成 · 工作台通知中心（2026-11-26 第 27 轮）

- 页面 `/notifications`（全部/未读筛选、标记已读、全部已读、删除）+ 导航栏铃铛（未读徽标 + 最近 6 条）。
- 请求层 `getNotifications` / `getUnreadNotificationCount` / `markNotificationRead` /
  `markAllNotificationsRead` / `deleteNotification`，类型 `NotificationItem`。
- 顺带修：`NEXT_PUBLIC_API_URL` 兜底值 8200 → 8000（无 `.env.local` 时前端连不上网关）；
  网关创建通知不传 `user_id` 时默认发给自己（原来写 `None`，导致通知谁也看不到）。
- 剩余：无实时推送（只有挂载/打开下拉时拉取）、前端没有发通知的入口、邮件/Webhook 仍未真正外发。

### ✅ 已完成 · 前端自动化测试（apps/web，2026-11-23 第 7 轮）

- 已补 17 项单测（请求层 10 + AuthProvider 7）+ 7 条 E2E（登录 3 + 工作流 4），见第 3 节第 7 轮。
- ✅ 第 21 轮：`apps/admin` 补了 28 项单测（请求层 / utils / AuthGate 可访问性），`pnpm --filter` 之外直接 `vitest run` 可跑。
- ✅ 第 21 轮：CI 新增 `smoke-tests` job（SQLite 起网关 → 等 `/health` → 跑 `test_gateway_smoke.py`），
  并把空测试目录导致的 exit 5 修掉。
- ✅ 第 23 轮：`apps/admin` 补了 8 项 Playwright E2E（登录/退出、五页导航、用户搜索空态、审计明细），
  并修掉「登出失败后界面仍显示已登录」的真 bug（见第 23 轮小节）。
- ✅ 第 24 轮：admin / web 的 E2E 已进 CI（`e2e-tests` job）。
- ✅ 第 27 轮：web 补 4 项通知请求层单测 + 2 项通知中心 E2E（未登录提示；造数据→已读→删除），现共 45 单测 + 9 E2E。
- 剩余（P2）：E2E 只跑 chromium，firefox/webkit 未纳入门禁；微服务冒烟（6 个服务）仍未进 CI。

### ✅ 已完成 · P1 CI 的安装阶段本身跑不通（2026-11-25 第 22 轮）

- 根 `pnpm-workspace.yaml` + 单一 `pnpm-lock.yaml` 已建，子锁文件已删；`turbo.json` 已改 `tasks`。
- 顺带修掉被迁移暴露的 `@radix-ui/react-button|input`（npm 上不存在）、`shared-types` 空测试目录、
  整套 ESLint/prettier 插件缺失、CI 的 `--coverage` 传参错误。
- 仍未在 Linux/真实 Actions 上跑过；`docker-build`、`release` 两个 job 未验证。

### ~~P1 · CI 的安装阶段本身跑不通（第 21 轮发现）~~

- **为什么做**：`ci.yml` 每个 job 第一步都是 `pnpm install --frozen-lockfile`，但仓库根目录既没有
  `pnpm-workspace.yaml` 也没有 `pnpm-lock.yaml`（只有 `apps/*/pnpm-lock.yaml`），pnpm 9 会直接报错退出；
  即使装上，`turbo.json` 用的是 turbo 1.x 的 `pipeline` 字段，turbo 2 启动会报「Found `pipeline` field」。
  也就是说 GitHub Actions 目前几乎不可能绿，只是没有远端触发所以没人发现。
- **怎么做**：新增根 `pnpm-workspace.yaml`（`packages/*`、`apps/*`；`services/*` 是 Python，不要放进去），
  删掉各 app 子锁文件、在根重新生成一份 `pnpm-lock.yaml`，`turbo.json` 的 `pipeline` 改名为 `tasks`；
  同时确认 `apps/admin`、`apps/web` 的 `pnpm install` 仍能正常装依赖（这一步会动本地 node_modules，需要单独一轮做）。
- **验收**：干净目录下 `pnpm install --frozen-lockfile && pnpm typecheck && pnpm test` 全绿；
  `apps/admin` / `apps/web` 的 dev server 仍能起。

### P2 · 其他

- ✅ 第 18 轮：Alembic baseline 已全部修好并实测；网关 / rag 启动自动迁移，其余 5 个服务仍走 `create_all`。
- ✅ 第 19 轮：CI 已加 `python-lint`（ruff，规则见根目录 `ruff.toml`），历史未使用 import 已清完。
- ✅ 第 20 轮：其余 5 个服务的启动建表也改为 Alembic（`DB_AUTO_MIGRATE`，旧库自动 `stamp head`）。
- ✅ 第 20 轮：管理后台视觉/可访问性回归（对比度、键盘可达、`scope="col"`、跳转链接、进度条语义、窄屏头部）。
- ✅ 第 20 轮：`infra/k8s` 补 auth/notification、修 admin 3000 与网关探针路径、补集群内服务地址；
  base + dev/staging/prod overlay 均可用 `kubectl kustomize` 渲染。
- ✅ 第 24 轮：E2E 已进 CI（`e2e-tests` job：SQLite 起网关 + 演示账号登录门禁 + admin 8 项 + web 9 项，
  `build.needs` 已包含它）。本机按同一串命令实跑 8/8、7/7。
- ✅ 第 25 轮：`release` job 已真正可用（`@changesets/cli` + `.changeset/` 配置 + 修掉 `GITHUB_ENV`
  heredoc 与 `changeset publish`/`NPM_TOKEN` 两处硬伤）；剩下 `docker-build` 一个 job 未验证。
- 剩余：`docker-build`（三个 Dockerfile）仍未验证（本机 Docker 守护进程未启动）。
- 剩余（部署前）：`infra/k8s/helm` 这套 chart 未被 ArgoCD 使用，本轮只修了 admin 端口，
  仍缺 auth/notification 模板与 `global.ingress.*` 等 values（本机无 helm，未做渲染验证）。
- 剩余：清单里没有 PostgreSQL / Redis / MinIO 自身的 Deployment（按外部托管假设写的），
  真上集群需要补依赖或改成连外部实例。

---

## 6. 已知缺口与风险

1. **SQLite 与 PostgreSQL 行为不同**：JSON 列在 SQLite 存文本、Enum 存 name；不要写 PG 专属 SQL（`->>`、`jsonb_*`、向量算子）到共享代码里。
2. **演示租户回退**：微服务不带头仍会写进 `00000000-…-0001`。签名（第 6 轮）已经堵住「直连端口冒充租户」，但**未配置 `SERVICE_API_KEY` 时验签不生效**（本地开发默认如此），生产必须显式配置同一密钥。
3. **构建会打断 dev server**：`next build` 覆盖 `.next`，之后 3001/3002 会 500，需要重启。
4. **Windows 脚本坑**：`.ps1` 必须 UTF-8 **带 BOM**（否则 PowerShell 5.1 读中文乱码并报解析错）；`cmd` 里必须写 `set "K=V"`，否则行尾空格会进变量值（`PYTHONUTF8=1 ` 会让 Python 直接崩）。
5. **冒烟测试依赖进程已启动**：先起网关/微服务再跑，否则跳过或失败。
6. **Docker Hub 在本机不可直连**：`registry-1.docker.io` 超时，只有提前缓存的镜像能用；
   拉新镜像前先确认 `docker images` 里有没有，或改用可用的镜像源（`minio/minio` 在 daocloud 源上被 denied）。
7. **compose 里有空变量**：未填 `COHERE_API_KEY` 时每条 compose 命令都会打一条 warning，属正常。

---

## 7. 交接：建议的下一步顺序

1. 用 `AGENTS.md` 的验证命令确认当前基线仍是绿的。
2. 拿 Docker 许可 → 跑通 P0-1（rag-service），把结果补进本文档第 3 节。
3. ~~做 P0-2（内部请求签名）~~ ✅ 第 6 轮已完成；下一步是把网关真正转发到微服务时用上它。
4. 再做 P1 的上传链路与前端测试。
5. 每轮结束：更新本文档、必要时同步 `overview.md` / `local-dev.md`。
