# AGENTS.md — 给后续 AI / 贡献者的工作约定

本文件是**必读的开工约定**。你（后续接手这个项目的 AI 或人）在动手前先读完它，
结束时按「收尾清单」交付。违反约定的改动一律视为未完成。

---

## 0. 每轮必须做的一件事

> **改动结束后，必须更新 [`docs/PROGRESS.md`](docs/PROGRESS.md)。**

具体要求：

1. 在「3. 已完成」顶部按 `YYYY-MM-DD · 第 N 轮：主题` 追加一节，写清：
   做了什么、**修掉了哪些真实 bug 及根因**、新增/修改了哪些文件、验证结果。
2. 勾掉已完成的待办；新发现的缺口按 P0/P1/P2 追加到「5. 待办 Backlog」，
   每条都要写 **为什么做 / 怎么做 / 验收标准**，不要只写标题。
3. 更新「4. 已验证的检查」里的最近一次结果（命令 + 数字），不要写「应该可以」。
4. 顶部「最后更新」日期同步改。
5. 如果改动影响了启动方式、端口、依赖，**同步** `docs/runbooks/local-dev.md`；
   影响了架构/数据流，**同步** `docs/architecture/overview.md`。

没有更新 PROGRESS.md 的改动 = 没有交接，视为未完成。

---

## 1. 开工前必读（按顺序）

1. `docs/PROGRESS.md` — 当前状态、已做、待办、已知风险。
2. `docs/architecture/overview.md` — 模块边界与数据流。
3. `docs/runbooks/local-dev.md` — 怎么起、端口、环境坑。
4. `README.md` / `PROJECT_PLAN.md` — 项目定位（偏作品集向，别过度工程化）。

---

## 2. 目录与端口速查

| 路径 | 说明 | 端口 |
|---|---|---|
| `services/api-gateway` | 主后端（FastAPI，单体，默认运行形态） | 8000 |
| `services/{auth,notification,llm,document,workflow,rag}-service` | 可独立拆分的微服务 | 8007 / 8006 / 8003 / 8004 / 8005 / 8001 |
| `apps/admin` | 管理后台（Next.js） | 3001 |
| `apps/web` | 用户工作台（Next.js） | 3002 |
| `packages/*` | 共享 TS 类型 / UI / 配置 | — |
| `tests/` | 语言无关冒烟测试（标准库 `unittest`） | — |
| `infra/` | Dockerfile、compose 挂载、k8s、terraform | — |

数据：本地默认 SQLite（`services/api-gateway/data/enterprise_ai.db` 等），
生产形态见 `docker-compose.yml`（PostgreSQL + pgvector、Redis、MinIO）。

---

## 3. 跑起来

```powershell
start-dev.cmd              # 网关 8000 + 工作台 3002 + 管理后台 3001
start-microservices.cmd    # 五个微服务（SQLite 模式，不需要 Docker）
```

手动启动网关（**必须在服务目录内**，SQLite 路径是相对的）：

```bash
cd services/api-gateway
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

演示账号 `admin@example.com / admin123`。

---

## 4. 验证命令（改完就跑到绿）

```bash
python tests/test_gateway_smoke.py            # 网关 20 项
python tests/test_microservices_smoke.py      # 微服务 7 项（未启动的自动跳过）

# 前端（依赖只在仓库根装一次：pnpm install）
pnpm lint && pnpm typecheck && pnpm test && pnpm build   # 79 项单测（admin 34 + web 45）

cd apps/admin && ./node_modules/.bin/vitest run           # 34 项单测，不需要后端

# E2E（Playwright，先起网关 8000；没起时依赖接口的用例自动 skip）
cd apps/admin && ./node_modules/.bin/playwright test      # 8 项：登录/退出、五页导航、用户搜索、审计明细
cd apps/web   && ./node_modules/.bin/playwright test      # 9 项：登录、工作流编辑器、通知中心
```

- Python 一律用 `services/api-gateway/.venv/Scripts/python.exe`（微服务共用这个 venv）。
- `npx tsc` 在本机不可用，用 `./node_modules/.bin/tsc`；装依赖用 `pnpm`（`npm install` 会坏）。
- 仓库是单一 pnpm workspace（根 `pnpm-workspace.yaml` 收 `apps/*` 与 `packages/*`，`services/*` 是 Python 不算），
  锁文件只有根目录一份：**不要在 `apps/*` 里单独 `pnpm install`**，否则 CI 的 `--frozen-lockfile` 会对不上。
- 读 JSON 要 UTF-8：`PYTHONUTF8=1 python …`，否则 Windows 控制台会 `JSONDecodeError`。
- 发版用 changesets：改完 `apps/*` / `packages/*` 就 `pnpm changeset` 加一条记录（规则见 `.changeset/README.md`）。
  `release` job 只在 `main` push 时开「版本 PR」，不发 npm；`pnpm changeset status` 需要 git 的 `main` 分支，
  当前项目目录不是 git 仓库，直接跑会报 diverged 错误。

---

## 5. 代码约定

- **审计**：所有管理类写操作走 `app/services/audit.py` 的 `record_audit(...)`，
  在业务事务内 `flush`；失败事件 `commit=True` 立即落库。`resource_id` 只放 UUID。
- **多租户**：微服务从 `app/core/context.py` 取 `current_tenant_id()` / `current_user_id()`，
  **不要**再写死 `00000000-0000-0000-0000-000000000001`（那是演示回退值，只在 context 里出现）。
  网关注入 `X-Tenant-Id` / `X-User-Id`；非法 UUID 由中间件直接 400。
- **可移植类型**：模型用 `sqlalchemy.JSON` / `sqlalchemy.Uuid`，
  不要用 `postgresql.JSONB` / `postgresql.UUID`（SQLite 会直接建表失败）。
- **索引**：列上已经有 `index=True` 时不要再写同名 `Index("ix_<table>_<col>", ...)`，
  否则 `create_all` 报 `index … already exists`。
- **对外字段名与 ORM 属性不一致时**用 Pydantic `validation_alias` / `serialization_alias`
  （例：ORM `meta` ↔ JSON `metadata`），不要改数据库列名。
- **就绪探针**：`/ready` 必须真检查依赖（现为 `SELECT 1`），失败返回 503，不要返回假的 ready。
- **前端**：两个 app 通过 Next rewrite 走同源 `/api/*` → `http://localhost:8000/api/*`，不要引入跨域直连。
- **通知已可转发**（`GATEWAY_PROXY_NOTIFICATIONS=true`）：两侧契约由 notification-service 的
  `002_gateway_contract` 对齐（UUID 主键 + `user_id/title/data/read`），不要再往网关的 UUID 里塞假 ID。
- 不要顺手大规模重构：这个项目的价值是「能跑通 + 能讲清楚」，优先修真实 bug。

---

## 6. 环境与平台坑（踩过的）

1. **PowerShell 5.1 需要 UTF-8 BOM**：`.ps1` 不带 BOM 会把中文读成乱码并报语法错。
2. **`cmd` 里写 `set "K=V"`**：`set K=V & next` 会把行尾空格吃进变量值，
   `PYTHONUTF8=1 ` 会让 Python 直接 `Fatal Python error`。
3. **`next build` 会覆盖 `.next`**：构建后 3001/3002 会 500，必须重启 dev server。
4. **端口占用是静默的**：Windows 上两个进程可以同时监听同一端口，请求会随机命中旧进程；
   启动前 `netstat -ano | grep ":8000"`，只杀确认过的 PID。
5. **不要用 `pkill -f` / `killall`**：模式可能匹配到自己；用具体 PID。
6. **Docker 守护进程可能没起**（`docker ps` 连不上 pipe）。需要容器时**先问用户**，不要擅自启动 Docker Desktop。

---

## 7. 不要做的事

- 不要 `git push`、不要部署、不要改生产配置（用户没明确要求就不做）。
- 不要为「跑起来」而删掉必需依赖、绑定或迁移脚本。
- 不要跳过/放宽测试断言来让检查变绿；失败就查根因。
- 不要在没启动服务时声称「已验证」；跳过就说跳过。
- 不要把 `SQLite` 下的行为当作 PostgreSQL 已验证（反之亦然）。

---

## 8. 收尾清单（每轮照做）

- [ ] 相关冒烟测试/类型检查跑到绿，记录真实数字
- [ ] `docs/PROGRESS.md`：新增一节 + 更新待办 + 更新最近验证结果 + 日期
- [ ] 启动方式/端口/依赖有变化 → 更新 `docs/runbooks/local-dev.md`
- [ ] 架构/数据流有变化 → 更新 `docs/architecture/overview.md`
- [ ] 交付说明里写清：改了什么、怎么验的、**哪些没验**（不要美化）
