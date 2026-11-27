# LLM Service

企业级多模型 LLM 网关服务，支持 OpenAI、Anthropic、Azure OpenAI、Ollama 等多个提供商，内置负载均衡、熔断器、成本追踪、流式输出。

## 架构概览

```
┌─────────────────┐
│   Client Request │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Load Balancer  │◀── Round Robin / Least Latency / Cost Aware
│  (Strategy)     │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────┐
│Provider│ │Provider│  Circuit Breaker per endpoint
│  A    │ │  B    │
└───┬───┘ └───┬───┘
    │         │
    ▼         ▼
┌─────────────────┐
│  Cost Tracking  │──▶ PostgreSQL (usage_records)
└─────────────────┘
```

## 核心功能

### 1. 多提供商支持
| 提供商 | 模型类型 | 特性 |
|--------|----------|------|
| OpenAI | Chat, Embedding | Functions, Vision, Streaming |
| Anthropic | Chat | System prompts, Streaming |
| Azure OpenAI | Chat, Embedding | 企业级 SLA, 私有部署 |
| Ollama | Chat, Embedding | 本地部署, 隐私优先 |

### 2. 负载均衡策略
- **Round Robin** (默认): 轮询分发
- **Least Latency**: 优选低延迟端点
- **Cost Aware**: 优选低成本模型
- **Random**: 随机分发

### 3. 熔断器模式
- **Closed**: 正常请求，失败计数
- **Open**: 失败阈值触发，快速失败
- **Half-Open**: 恢复期尝试少量请求

### 4. 成本追踪
- 每请求记录：tokens、延迟、预估成本 (micro-USD)
- 按模型/提供商/用户/时间聚合
- OpenAI 兼容的 `/v1/models` 列表端点

### 5. API 兼容性
- 完全兼容 OpenAI Chat Completions API
- 支持流式 (`stream: true`) 和非流式
- Embeddings API 兼容

## 快速开始

### 1. 安装依赖
```bash
cd services/llm-service
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入 API Keys
```

### 3. 运行迁移
```bash
alembic upgrade head
```

### 4. 启动服务
```bash
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8003
```

### 5. 配置提供商和模型
```bash
# 创建 OpenAI 提供商
curl -X POST http://localhost:8003/api/v1/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "openai-main",
    "provider_type": "openai",
    "api_key": "sk-xxx",
    "priority": 10
  }'

# 创建模型配置
curl -X POST http://localhost:8003/api/v1/models \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "<provider-uuid>",
    "name": "gpt-4o-mini",
    "display_name": "GPT-4o Mini",
    "model_type": "chat",
    "context_window": 128000,
    "max_output_tokens": 4096,
    "supports_streaming": true,
    "input_cost_per_1k": 150000,
    "output_cost_per_1k": 600000,
    "is_default": true
  }'
```

### 6. 调用聊天完成
```bash
curl -X POST http://localhost:8003/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

### 7. 流式输出
```bash
curl -X POST http://localhost:8003/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Write a poem"}],
    "stream": true
  }' --no-buffer
```

## 配置说明

### 提供商配置
```bash
# OpenAI
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_API_BASE=https://api.anthropic.com

# Azure OpenAI
AZURE_OPENAI_API_KEY=xxx
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
```

### 负载均衡
```bash
LB_STRATEGY=round_robin  # round_robin, least_latency, cost_aware, random
```

### 熔断器
```bash
CB_FAILURE_THRESHOLD=5      # 连续失败次数触发熔断
CB_RECOVERY_TIMEOUT=60      # 恢复超时(秒)
CB_HALF_OPEN_REQUESTS=3     # 半开状态允许请求数
```

### 成本追踪
```bash
COST_TRACKING_ENABLED=true
COST_PER_1K_TOKENS='{"gpt-4o": {"input": 5000000, "output": 15000000}, ...}'  # micro-USD
```

## 数据库模型

| 表 | 说明 |
|----|------|
| `provider_configs` | 提供商配置 (API Key, 端点, 限流, 状态) |
| `model_configs` | 模型配置 (类型, 上下文窗口, 成本, 能力) |
| `usage_records` | 使用记录 (tokens, 成本, 延迟, 状态) |

## 监控指标

- `llm_requests_total` - 请求总数 (model, provider, status)
- `llm_request_duration_seconds` - 请求延迟直方图
- `llm_tokens_total` - Token 使用量 (prompt/completion)
- `llm_cost_usd_total` - 成本累计 (USD)
- `llm_circuit_breaker_state` - 熔断器状态 (0=closed, 1=half-open, 2=open)

## 部署

### Docker
```bash
docker build -f infra/docker/llm-service/Dockerfile -t enterprise-ai/llm-service .
docker run -p 8003:8003 --env-file .env enterprise-ai/llm-service
```

### Docker Compose
```bash
docker-compose up llm-service
```

## 开发指南

### 添加新提供商
1. 在 `ProviderType` 枚举中添加类型
2. 在 `app/services/providers.py` 中实现 `BaseProvider` 子类
3. 在 `ProviderFactory._providers` 中注册

### 自定义负载均衡策略
继承 `LoadBalancingStrategy` 枚举并在 `LoadBalancer.get_endpoint` 中实现逻辑。

### 成本计算自定义
修改 `LLMService._record_usage` 中的成本计算逻辑。

## 故障排查

### 熔断器频繁打开
- 检查提供商 API Key 是否有效
- 检查网络连通性
- 调整 `CB_FAILURE_THRESHOLD` 和 `CB_RECOVERY_TIMEOUT`

### 成本为 0
- 确保 `COST_TRACKING_ENABLED=true`
- 检查 `model_configs` 中的 `input_cost_per_1k` / `output_cost_per_1k` 是否设置 (单位: micro-USD)

### 流式输出不工作
- 确认模型配置 `supports_streaming=true`
- 检查客户端是否正确处理 SSE 格式

## 许可证
MIT