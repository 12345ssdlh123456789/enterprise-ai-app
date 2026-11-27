# 服务拆分现状与资源归属矩阵

> 最后更新：2026-11-26（第 26 轮）
>
> 这份文档回答三个问题：**哪些资源已经能按服务边界切走、哪些还留在网关、为什么**。
> 结论先行：**默认形态是网关单体**，拆分在 document / workflow / notification 三块做过并验证过；
> 其余资源不是"还没来得及写适配器"，而是契约或数据归属还没定。

---

## 1. 判定标准：什么算"可拆"

一个资源能交给微服务，必须同时满足三条：

1. **数据归属单一**：这份数据只有一个写入方，不存在两个服务各存一份还要互相同步。
2. **契约可无损映射**：网关对外的字段、分页、错误体能在适配层双向转换，前端不用改。
3. **身份与权限能传导**：租户/用户身份、签名、RBAC 在代理层能补齐（第 14 轮已补 RBAC）。

少任何一条就不拆——宁可留在网关，也不要做"半拆"，因为半拆会产生两套真相。

---

## 2. 服务与端口

| 服务 | 端口 | 存储 | 备注 |
| --- | --- | --- | --- |
| API 网关 | 8000 | SQLite（网关库） | 唯一对外入口，JWT + RBAC + 审计 |
| 用户工作台 | 3002 | — | Next.js，经 `/api/*` rewrite 走网关 |
| 管理后台 | 3001 | — | Next.js |
| rag-service | 8001 | PostgreSQL + pgvector | 向量检索依赖 pgvector；另用 Redis |
| llm-service | 8003 | SQLite `llm_dev.db` | provider / model / chat / usage |
| document-service | 8004 | SQLite `document_dev.db` + `./data/storage` | 默认 `STORAGE_PROVIDER=local`，可切 MinIO/S3 |
| workflow-service | 8005 | SQLite `workflow_dev.db` | 图定义、执行、执行记录 |
| notification-service | 8006 | SQLite `notification.db` | 可选 SMTP，未配置只入库不外发 |
| auth-service | 8007 | SQLite `auth.db` | 独立认证服务（默认端口 8000，需 `PORT=8007`） |

网关侧的开关与地址：

```env
# 默认都关；打开即把对应路径交给微服务
GATEWAY_PROXY_DOCUMENTS=false
GATEWAY_PROXY_WORKFLOWS=false

DOCUMENT_SERVICE_URL=http://127.0.0.1:8004
WORKFLOW_SERVICE_URL=http://127.0.0.1:8005
RAG_SERVICE_URL=http://127.0.0.1:8001
LLM_SERVICE_URL=http://127.0.0.1:8003
AUTH_SERVICE_URL=http://127.0.0.1:8007
```

> 转发要求网关与微服务配置**同一个 `SERVICE_API_KEY`**，否则微服务返回 401「签名不匹配」。

---

## 3. 资源归属矩阵

状态：✅ 已拆并验证 ｜ 🟡 可拆但未接 ｜ ❌ 不拆（留在网关）

| 资源 | 归属 | 状态 | 网关路径 | 说明 |
| --- | --- | --- | --- | --- |
| 认证 / 登录 / 刷新 / 改密 | 网关（可切 auth-service） | ❌ | `/auth/*` | auth-service 已独立存在并冒烟通过，但网关自己也能签发 JWT；切换要改前端登录链路与密钥分发 |
| 用户 / 租户 | 网关 | ❌ | `/users`、`/tenants` | 与 RBAC、审计、KB 归属强耦合 |
| 知识库（KB） | 网关 | ❌ | `/knowledge-bases` | **枢纽资源**：文档、对话、检索、ingest、internal API 共 9 个网关模块引用它 |
| 文档 | document-service | ✅ | `/documents`、`/upload`、`/download` | `GATEWAY_PROXY_DOCUMENTS`，流式上传/下载 + 契约适配 + 租户校验 + RBAC |
| 文档分块 | 网关（自己的库） | ❌ | `/documents/{id}/chunks` | 转发开启时明确 501，不假装成功 |
| 检索 | 网关 | 🟡 | `/retrieval/search` | 网关有自己的检索实现；rag 也有 `/retrieval/search`，但两边 KB ID 不互通 |
| 对话 / 聊天 | 网关 | ❌ | `/conversations`、`/chat/completions` | 对话引用 KB 与检索结果，属于网关内的编排逻辑 |
| 模型目录 / Provider | 网关（可切 llm-service） | 🟡 | `/models` | 网关 `/models` 是"模型目录"（含定价、启用状态）；llm 是 `/providers` + `/models` + `/chat/completions` |
| 工作流 | workflow-service | ✅ | `/workflows` | `GATEWAY_PROXY_WORKFLOWS`，图结构双向转换 |
| 工作流发布撤回 | 微服务无此接口 | ❌ | `/workflows/{id}/unpublish` | 转发时返回 501；需要微服务补接口才能拆 |
| 通知 | notification-service | ✅ | `/notifications` | `GATEWAY_PROXY_NOTIFICATIONS`，第 26 轮对齐 UUID 契约后接入（见 §5.1） |
| 审计 / 成本 / API Key / 系统配置 | 网关 | ❌ | `/audit-logs`、`/costs`、`/api-keys`、`/configs` | 管理面横切数据，天然属于网关 |

---

## 4. 已接入的两组：适配点在哪

代码集中在 `services/api-gateway/app/api/v1/`：

| 文件 | 作用 |
| --- | --- |
| `proxy.py` | document 路由分发、流式转发、RBAC、签名注入、信封包装 |
| `proxy_adapters.py` | 两侧字段/分页/图结构双向转换 |
| `proxy_workflows.py` | workflow 路由分发 |

### 4.1 文档

- 响应统一包回网关 `{success, data, error, meta}`；字段名用网关的 `file_name / mime_type / type`。
- 列表：用微服务的 `X-Total-Count` 拼网关分页对象；`skip/limit` ↔ `page/page_size`。
- 上传/下载：`request.stream()` → `StreamingResponse`，不整块缓冲。
- `reprocess` → 微服务 `process`；DELETE 的 204 转成网关 200。
- **降级**：`search` / `type` 过滤微服务不支持 → 忽略；`/documents/{id}/chunks` → 501。
- **统计**：转发开启时 KB 的计数与最近文档由 `POST /api/v1/internal/kb-stats` 提供（第 15 轮）。

### 4.2 工作流

- 节点：网关 `{id, type 大写, name, position, config, inputs[{id}]}` ↔ 微服务 `{id, type 小写, position, config, inputs[str]}`；`name` 存在微服务的 `config.name` 里。
- 边：`source_node_id/source_port_id/target_node_id/target_port_id` ↔ `source/source_handle/target/target_handle`。
- 执行：`{input|input_data}` → `{input_data, async_mode}`；节点级日志在 `/executions/{id}/logs`，网关未拉取。
- **降级**：`unpublish` → 501。

---

## 5. 未接入的两个：具体卡在哪

### 5.1 ✅ notification-service —— 第 26 轮已接入（选的是「服务侧改契约」）

原来的卡点：网关是 UUID 主键 + `user_id/title/data/read`，notification-service 是 `int` 主键 +
`recipient_id/subject`；假造 UUID 会让「已读 / 删除 / 详情」按 ID 找不到记录。

第 26 轮选了 **(b) 服务侧改契约**（前端与网关数据都不动），具体做法：

| | 网关（不变） | notification-service（改后） |
| --- | --- | --- |
| 主键 | UUID | `Uuid` 主键（迁移 `002_gateway_contract`，行 ID 会变） |
| 收件人 | `user_id: UUID` | `user_id: UUID`（外部收件人另存 `recipient_id`） |
| 标题/正文 | `title` + `data` | 同名；旧的 `subject` 仍可传入（等价 `title`） |
| 已读 | `read: bool` | `read` + `read_at`；`PATCH /{id}/read`、`PATCH /read-all` |
| 类型 / 渠道 | `type` / `channel` 枚举 | 同名字符串（默认 `INFO` / `IN_APP`） |

- 转发层：`services/api-gateway/app/api/v1/proxy_notifications.py`（开关 `GATEWAY_PROXY_NOTIFICATIONS`），
  字段映射在 `proxy_adapters.to_gateway_notification()`，**不再伪造 ID**。
- 隔离：服务按 `X-User-Id` 过滤（`app/core/context.py`），直连 8006 也读不到别人的通知；非法 UUID 直接 400。
- 写入方：第 28 轮起网关的 `app/services/notify.py` 是唯一出口 —— 文档解析完成/失败、工作流执行结束都会写一条；
  `GATEWAY_PROXY_NOTIFICATIONS=true` 时它带签名 POST 给本服务，否则写网关自己的 `notifications` 表。
  两个方向都实测过（见 `docs/PROGRESS.md` 第 28 轮）。
- 权限：与网关自带路由一致——列表/已读/删除登录即可，**创建要求 ADMIN / SUPER_ADMIN**（转发层同样校验）。
- 降级：`GET /notifications/{id}`（网关本来就没有详情路由）在转发模式下返回 501。
- 仍保留的差异：`recipient_type` / `status`（投递状态）/ 邮件-webhook 投递是服务侧能力，网关不暴露；
  邮件/Webhook 真正发送仍未实现（原来就是 TODO）。

### 5.2 llm-service —— "模型目录"和"模型网关"不是一回事

- 网关 `/models`：管理员维护的目录（名称、供应商、定价、是否启用），被计费与对话引用。
- llm-service：`/providers`（含健康检查）、`/models`、`/chat/completions`、`/usage/records`、`/usage/cost-summary`。

直接转发会让管理后台的模型页变空且字段对不上。真正值得接的是 **`/chat/completions`**（OpenAI 兼容），
但它要先把"模型目录归属"定下来——否则网关不知道某个模型该路由到哪个 provider。

### 5.3 rag-service —— 两套知识库，ID 不互通

- 网关有 `knowledge_bases` + 自己的检索与 ingest；rag 也有 `/knowledge-bases`、`/documents`、`/retrieval/search`、`/embeddings`。
- 两边的 KB ID 属于不同库，网关的 KB ID 拿到 rag 查不到东西；网关 KB 响应里的 `document_count / chunk_count` 是网关侧统计。
- 因此 **rag 不能只"接检索"**：要么 KB 整体归 rag（网关变聚合层），要么保持两套并明确禁止交叉引用。

---

## 6. 开关组合的实际行为

| `PROXY_DOCUMENTS` | `PROXY_WORKFLOWS` | 文档写在哪 | KB 计数来源 | 说明 |
| --- | --- | --- | --- | --- |
| false | false | 网关库 | 网关库 | 默认单体，演示数据完整 |
| true | false | document-service | 微服务（内部接口） | 网关 `documents` 表不再更新，`/chunks` 501 |
| false | true | 网关库 | 网关库 | 工作流由微服务持有 |
| true | true | document-service | 微服务（内部接口） | 冒烟与页面验证使用的组合 |

两种模式**数据不互通**：切换开关不会迁移已有数据，演示前请选定一种并保持一致。

`GATEWAY_PROXY_NOTIFICATIONS` 是独立开关：打开后 `/notifications` 全部由 notification-service 持有
（网关自己的 `notifications` 表不再写入），列表 / 未读数 / 已读 / 删除都走转发；
与文档、工作流的开关互不影响。

---

## 7. 如果将来要做"拆分态"：最小路径与代价

以 KB 归 rag 为例（另一种是全部留在网关，即当前的演示态）：

1. **定归属**：KB / 文档 / chunk / 检索结果全部由 rag 持有，网关只保留用户、租户、审计。
2. **迁数据**：网关 `knowledge_bases`、`documents` 迁到 rag 的 Postgres（或让 rag 支持同一库）；文档对象迁到同一存储。
3. **改网关**：KB、检索、对话的上下文拼装改为聚合调用；`internal.py` 的 KB 查询改走 rag。
4. **改前端**：`apps/web` 的 5 个知识库相关页面按新字段调整（当前直接依赖网关结构）。
5. **双写观察期**：至少一个迭代内保留旧读路径，核对计数、检索命中与引用来源。

工作量估值：**1–2 周**（含迁移脚本与回归），风险集中在"对话引用历史"与"双库一致性"。
收益是可独立扩容向量检索与多团队并行；代价是演示链路复杂度上升。
**除非出现真实需求，不建议现在做。**

---

## 8. 验证入口

| 用例 | 覆盖 |
| --- | --- |
| `tests/test_microservices_smoke.py::test_gateway_forwards_documents_with_jwt_identity` | 文档转发、流式上传下载、契约字段、租户来自 JWT |
| `::test_gateway_forwards_workflows` | 工作流图结构双向转换、validate、publish、unpublish→501 |
| `::test_proxy_enforces_gateway_rbac` | VIEWER 读 200 / 写 403（文档与工作流） |
| `::test_kb_stats_follow_proxied_documents` | KB 统计跟随微服务、软删除后同内容重传复活 |
| `tests/test_gateway_smoke.py` | 网关单体 13 项（转发开关开启时也不回归） |

启动与开关用法见 `docs/runbooks/local-dev.md`；进度与已知限制见 `docs/PROGRESS.md`。
