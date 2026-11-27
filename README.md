# Enterprise AI App

> 企业级 AI 应用开发框架 - 从 0 到 1 的完整实践项目


[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **接手开发先读**：[`AGENTS.md`](AGENTS.md)（工作约定）→ [`docs/PROGRESS.md`](docs/PROGRESS.md)（现在能跑什么 / 已做完 / 待办）。
> 每轮改动结束都要把进度与待办写回 `docs/PROGRESS.md`。

## 🎯 项目简介

本项目是一个**企业级 AI 应用开发框架**，展示了从基础设施搭建到核心 AI 能力构建、业务功能开发、前端交互、DevOps 落地的完整流程。适合作为求职作品集、团队技术选型参考、或企业内部 AI 平台的起步模板。

### 核心特性

| 领域 | 技术栈 | 说明 |
|------|--------|------|
| **后端框架** | FastAPI / Node.js | 高性能、类型安全、自动生成 API 文档 |
| **数据库** | PostgreSQL + pgvector | 关系型数据 + 向量检索一体化 |
| **缓存/队列** | Redis + Celery | 高性能缓存、异步任务处理 |
| **AI/ML** | LangChain / LlamaIndex / 原生 SDK | 多模型支持、RAG 管线、Agent 编排 |
| **前端** | Next.js 14 + TypeScript + Tailwind | App Router、流式响应、组件化设计 |
| **基础设施** | Docker + Kubernetes + GitHub Actions | 容器化、GitOps、CI/CD 全自动化 |
| **可观测性** | Prometheus + Grafana + Jaeger | 指标监控、链路追踪、日志聚合 |

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        客户端层 (Web / Mobile / API)                   │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────┐
│                        API Gateway (统一入口、限流、认证、路由)           │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│  Auth Service │         │  RAG Service  │         │  LLM Service  │
│  (认证授权)    │         │  (知识检索)    │         │  (模型代理)    │
└───────────────┘         └───────────────┘         └───────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│ Document Svc  │         │ Workflow Svc  │         │ Notification  │
│ (文档处理)     │         │ (工作流编排)   │         │ (通知服务)     │
└───────────────┘         └───────────────┘         └───────────────┘
        │                         │                         │
        └─────────────────────────┼─────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│  PostgreSQL   │         │    Redis      │         │   MinIO/S3    │
│  (主数据+向量) │         │  (缓存/队列)   │         │  (对象存储)    │
└───────────────┘         └───────────────┘         └───────────────┘
```

## 📁 目录结构

```
enterprise-ai-app/
├── .github/workflows/          # CI/CD 流水线
├── apps/
│   ├── web/                    # 用户前端 (Next.js)
│   └── admin/                  # 管理后台 (Next.js)
├── packages/                   # 共享包
│   ├── shared-types/           # TypeScript/Python 共享类型
│   ├── config/                 # 统一配置管理
│   └── ui-components/          # 共享 UI 组件库
├── services/                   # 微服务
│   ├── api-gateway/            # API 网关
│   ├── auth-service/           # 认证服务
│   ├── rag-service/            # RAG 核心服务
│   ├── llm-service/            # LLM 代理服务
│   ├── document-service/       # 文档处理服务
│   ├── workflow-service/       # 工作流编排服务
│   └── notification-service/   # 通知服务
├── infra/                      # 基础设施即代码
│   ├── docker/                 # Dockerfile & docker-compose
│   ├── k8s/                    # Kubernetes 配置
│   └── terraform/              # Terraform 配置
├── docs/                       # 文档
│   ├── architecture/           # 架构设计文档 (ADR)
│   ├── api/                    # API 文档
│   └── runbooks/               # 运维手册
├── scripts/                    # 运维脚本
├── tests/                      # 集成测试/E2E测试
├── docker-compose.yml          # 本地开发环境
├── turbo.json                  # Turborepo 配置
├── package.json                # 根包配置
└── PROJECT_PLAN.md             # 项目详细计划
```

## 🚀 快速开始

### 前置要求

- **Node.js** >= 20.0.0
- **Python** >= 3.11
- **pnpm** >= 9.0.0
- **Docker** >= 24.0 + Docker Compose >= 2.0
- **PostgreSQL** 16 + pgvector (或使用 Docker)
- **Redis** 7+

### 1. 克隆并安装依赖

```bash
git clone https://github.com/12345ssdlh123456789/enterprise-ai-app.git
cd enterprise-ai-app

# 安装根依赖
pnpm install
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 填入你的 API Key
# 必填: OPENAI_API_KEY 或 ANTHROPIC_API_KEY
# 可选: AZURE_OPENAI_*, OLLAMA_BASE_URL 等
```

### 3. 启动基础设施

```bash
# 启动 PostgreSQL、Redis、MinIO 等
pnpm docker:up

# 查看日志
pnpm docker:logs

# 检查服务状态
docker-compose ps
```

### 4. 初始化数据库

```bash
# 数据库会在首次启动时自动执行 init.sql
# 如需手动执行:
docker-compose exec postgres psql -U enterprise_ai -d enterprise_ai -f /docker-entrypoint-initdb.d/init.sql
```

### 5. 启动开发服务器

```bash
# 启动所有服务 (前端 + 后端)
pnpm dev

# 或单独启动
cd apps/web   && pnpm dev          # 用户工作台 :3002
cd apps/admin && pnpm install && pnpm dev   # 管理后台 :3001
cd services/api-gateway && python -m uvicorn app.main:app --port 8000  # API 网关 :8000
```

### 6. 访问应用

| 服务 | 地址 | 说明 |
|------|------|------|
| Web 前端 | http://localhost:3000 | 用户交互界面 |
| Admin 后台 | http://localhost:3001 | 管理员界面 |
| API 网关 | http://localhost:8000 | REST API + WebSocket |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |
| Mailpit | http://localhost:8025 | 邮件测试界面 |
| Grafana | http://localhost:3002 | admin / admin123 (需 `--profile monitoring`) |
| Jaeger | http://localhost:16686 | 链路追踪 (需 `--profile monitoring`) |

### 7. 测试与文档

```bash
python tests/test_gateway_smoke.py     # 网关冒烟：13 项
cd apps/web && pnpm test               # 前端单元测试
```

- 架构说明：`docs/architecture/overview.md`
- API 说明：`docs/api/README.md`
- 本地排障：`docs/runbooks/local-dev.md`

## 🔧 开发指南

### 常用命令

```bash
# 代码检查
pnpm lint          # ESLint 检查
pnpm typecheck     # TypeScript 类型检查

# 测试
pnpm test          # 运行所有测试
pnpm test:watch    # 监听模式

# 数据库
pnpm db:generate   # 生成 Prisma Client
pnpm db:migrate    # 运行迁移
pnpm db:studio     # 打开 Prisma Studio

# 构建
pnpm build         # 构建所有包
pnpm build --filter=web  # 仅构建 web

# Docker
pnpm docker:up     # 启动基础设施
pnpm docker:down   # 停止基础设施
pnpm docker:logs   # 查看日志
```

### 添加新服务

```bash
# 1. 创建服务目录
mkdir -p services/new-service/{src,tests}

# 2. 创建 package.json (参考现有服务)

# 3. 在 turbo.json 中添加 pipeline 配置

# 4. 在 docker-compose.yml 中添加服务定义

# 5. 创建 Dockerfile (参考 infra/docker/)

# 6. 在根 package.json workspaces 中添加路径
```

### 代码规范

- **TypeScript**: Strict 模式、ESLint + Prettier
- **Python**: Ruff + Black + MyPy
- **Git 提交**: Conventional Commits (feat:, fix:, chore:, docs:, etc.)
- **分支策略**: GitHub Flow (main + feature branches)

## 📚 核心功能模块

### 1. 认证授权系统 (`auth-service`)
- JWT Access/Refresh Token
- RBAC 角色权限控制 (Super Admin / Admin / Member / Viewer)
- 多租户隔离
- OAuth2 / SSO 支持 (Google, GitHub, Microsoft, SAML, OIDC)
- 审计日志

### 2. RAG 知识检索 (`rag-service`)
- **文档解析**: PDF, Word, Markdown, HTML, CSV, JSON, PPTX, XLSX
- **智能分块**: 语义分块、固定大小、递归分块、Markdown 结构感知
- **嵌入模型**: OpenAI text-embedding-3, 本地模型
- **向量检索**: pgvector (HNSW/IVFFlat)、混合检索 (BM25 + 向量)
- **重排序**: Cross-Encoder、Cohere Rerank、本地重排序
- **生成增强**: 引用溯源、流式输出、Token 计费

### 3. LLM 统一代理 (`llm-service`)
- 多提供商支持: OpenAI, Anthropic, Azure OpenAI, Ollama, vLLM
- 统一接口: Chat, Embedding, Rerank, Vision
- 负载均衡、故障转移、重试策略
- Token 成本追踪、预算控制
- 提示词模板管理、版本控制

### 4. 工作流编排 (`workflow-service`)
- 可视化 DAG 编排器
- 节点类型: LLM、检索、条件、HTTP、代码、人工审批
- 变量系统、并行执行、错误处理
- 执行历史、调试回放

### 5. 文档处理 (`document-service`)
- 多格式解析 (Apache Tika / LibreOffice / 专用库)
- OCR 支持 (Tesseract)
- 元数据提取、结构化解析
- 异步处理、进度回调

## 🐳 生产部署

### Kubernetes 部署

```bash
# 1. 构建并推送镜像
./scripts/build-and-push.sh v1.0.0

# 2. 部署到集群
kubectl apply -k infra/k8s/overlays/production

# 3. 验证部署
kubectl get pods -n enterprise-ai
```

### Helm 部署 (推荐)

```bash
# 添加仓库
helm repo add enterprise-ai https://charts.enterprise-ai.app

# 安装
helm install enterprise-ai enterprise-ai/enterprise-ai \
  --namespace enterprise-ai \
  --create-namespace \
  -f values-production.yaml
```

### 环境变量管理

生产环境建议使用:
- **HashiCorp Vault** - 密钥管理
- **Sealed Secrets** - Kubernetes Secret 加密
- **External Secrets Operator** - 同步外部密钥

## 📊 监控与运维

### 关键指标

| 指标 | 说明 | 告警阈值 |
|------|------|----------|
| `http_request_duration_seconds` | API 延迟 | P99 > 2s |
| `http_requests_total` | 请求量/错误率 | 5xx > 1% |
| `rag_retrieval_latency_seconds` | 检索延迟 | P95 > 1s |
| `llm_token_usage_total` | Token 消耗 | 日预算 > 80% |
| `celery_task_duration_seconds` | 任务执行时间 | > 5min |
| `postgres_connections_active` | 数据库连接数 | > 80% pool |

### 日志查询

```bash
# 查看特定服务日志
docker-compose logs -f api-gateway

# Kubernetes
kubectl logs -f deployment/api-gateway -n enterprise-ai

# 结构化日志查询 (Loki/Grafana)
{service="api-gateway"} |= "error" | json
```

### 链路追踪

所有服务集成 OpenTelemetry，自动传播 `traceparent` Header，在 Jaeger/UI 中可查看完整调用链。

## 💰 成本控制

- **Token 预算**: 租户级 日/月预算，超限自动限流
- **模型路由**: 简单任务用小模型，复杂任务用大模型
- **缓存策略**: Embedding 缓存、查询缓存、响应缓存
- **成本仪表盘**: 实时展示各模型、各租户、各功能成本

## 🔒 安全合规

- **数据加密**: 传输加密 (TLS 1.3)、静态加密 (AES-256)
- **最小权限**: 服务间 mTLS、数据库最小权限账号
- **审计合规**: 所有敏感操作记录审计日志，不可篡改
- **数据脱敏**: PII 检测与脱敏、输出内容安全过滤
- **漏洞扫描**: CI 集成 Trivy、Dependabot、CodeQL

## 🧪 测试策略

```
测试金字塔:
       /\
      /  \     E2E Tests (Playwright) - 关键用户旅程
     /----\    Integration Tests - 服务间交互、数据库
    /      \   Unit Tests (Vitest/Pytest) - 业务逻辑、工具函数
   /--------\
```

```bash
# 运行测试
pnpm test                    # 单元测试
pnpm test:integration        # 集成测试 (需基础设施)
pnpm test:e2e               # E2E 测试 (需完整环境)
```

## 📖 文档

- [服务拆分现状与资源归属](docs/architecture/service-split.md)
- [架构决策记录 (ADR)](docs/architecture/adr/)
- [API 文档](docs/api/) - Swagger/OpenAPI 规范
- [部署指南](docs/runbooks/deployment.md)
- [运维手册](docs/runbooks/)
- [开发指南](docs/development/)

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支: `git checkout -b feat/amazing-feature`
3. 提交变更: `git commit -m 'feat: add amazing feature'`
4. 推送分支: `git push origin feat/amazing-feature`
5. 创建 Pull Request

### 提交规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代、快速的 Web 框架
- [Next.js](https://nextjs.org/) - React 全栈框架
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量扩展
- [LangChain](https://www.langchain.com/) - LLM 应用开发框架
- [shadcn/ui](https://ui.shadcn.com/) - 精美可访问的组件库
- [Turborepo](https://turbo.build/repo) - 高性能构建系统

---

**Star ⭐ 这个项目如果对你有帮助！**

有问题欢迎提 [Issue](https://github.com/12345ssdlh123456789/enterprise-ai-app/issues) 或参与讨论。