# RAG Service

企业级 RAG (Retrieval-Augmented Generation) 管线服务，提供文档处理、混合检索、重排序功能。

## 架构概览

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Document Ingest │────▶│  Chunking & Embed│────▶│  Vector Store   │
│  (PDF, DOCX,     │     │  (Recursive +    │     │  (pgvector +    │
│   TXT, MD)       │     │   tiktoken)      │     │   HNSW Index)   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
┌─────────────────┐     ┌──────────────────┐              │
│   User Query    │────▶│  Hybrid Retrieval│◀─────────────┘
│                 │     │  (BM25 + Vector  │
└─────────────────┘     │   + RRF Fusion)  │
                        └────────┬─────────┘
                                 │
                        ┌────────▼────────┐
                        │  Cohere Rerank  │
                        │  (v3.5)         │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  LLM Generation │
                        │  (via LLM Svc)  │
                        └─────────────────┘
```

## 核心功能

### 1. 文档处理管线
- **多格式解析**: PDF (pdfplumber), DOCX (python-docx), TXT, Markdown
- **智能分块**: 递归字符分块 + tiktoken token 计数 (chunk_size=1000, overlap=200)
- **嵌入生成**: 支持任意 OpenAI 兼容 API (OpenAI, Voyage, Jina, Cohere 等)
- **向量存储**: PostgreSQL + pgvector, HNSW 索引加速

### 2. 混合检索
- **向量检索**: 余弦相似度, pgvector HNSW 索引
- **关键词检索**: BM25 (rank-bm25), 持久化索引
- **融合算法**: RRF (Reciprocal Rank Fusion, k=60) - 无需调参, 鲁棒性强
- **重排序**: Cohere Rerank v3.5 (可选)

### 3. API 接口
| 模块 | 路径 | 功能 |
|------|------|------|
| Knowledge Bases | `/api/v1/knowledge-bases` | KB CRUD, 配置管理 |
| Documents | `/api/v1/documents` | 文档上传、处理、分块查看 |
| Retrieval | `/api/v1/retrieval/search` | 混合检索 + 重排 |
| Embeddings | `/api/v1/embeddings` | 批量嵌入生成 |

## 快速开始

### 1. 安装依赖
```bash
cd services/rag-service
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入配置
```

关键配置：
- `DATABASE_URL` - PostgreSQL + pgvector 连接
- `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` - 嵌入模型配置
- `COHERE_API_KEY` - Cohere Rerank API Key (可选)

### 3. 运行迁移
```bash
alembic upgrade head
```

### 4. 启动服务
```bash
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### 5. 访问 API 文档
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## 配置说明

### 嵌入模型配置
支持任意 OpenAI 兼容的嵌入 API：

```bash
# OpenAI
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_API_BASE=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

# Voyage AI
EMBEDDING_API_KEY=pa-xxx
EMBEDDING_API_BASE=https://api.voyageai.com/v1
EMBEDDING_MODEL=voyage-3
EMBEDDING_DIM=1024

# Jina AI
EMBEDDING_API_KEY=jina_xxx
EMBEDDING_API_BASE=https://api.jina.ai/v1
EMBEDDING_MODEL=jina-embeddings-v3
EMBEDDING_DIM=1024
```

### 分块配置
```bash
CHUNK_SIZE=1000      # 目标 chunk token 数
CHUNK_OVERLAP=200    # 重叠 token 数
CHUNK_MIN_SIZE=100   # 最小 chunk token 数
```

### 检索配置
```bash
RETRIEVAL_TOP_K=20   # 初始检索数量 (vector + bm25 各取 top-k)
RETRIEVAL_FINAL_K=5  # 最终返回数量
RRF_K=60             # RRF 融合参数
```

### 重排序配置
```bash
COHERE_API_KEY=xxx   # Cohere API Key
RERANK_MODEL=rerank-v3.5
RERANK_TOP_K=10      # 重排前取多少候选
```

## 数据库模型

| 表 | 说明 |
|----|------|
| `knowledge_bases` | 知识库配置 (嵌入模型、分块参数、检索参数) |
| `documents` | 文档元数据 (状态、哈希、分块统计) |
| `document_chunks` | 文档分块 (内容、向量、元数据) |

## 监控指标

- `rag_documents_processed_total` - 处理文档总数
- `rag_chunks_created_total` - 创建分块总数
- `rag_retrieval_duration_seconds` - 检索延迟直方图
- `rag_rerank_duration_seconds` - 重排延迟直方图
- `rag_embedding_errors_total` - 嵌入错误计数

## 部署

### Docker
```bash
docker build -f infra/docker/rag-service/Dockerfile -t enterprise-ai/rag-service .
docker run -p 8001:8001 --env-file .env enterprise-ai/rag-service
```

### Docker Compose (开发)
```bash
docker-compose up rag-service
```

## 开发指南

### 添加新的文档解析器
在 `app/services/document_processor.py` 中扩展 `_extract_text` 方法。

### 自定义分块策略
继承 `Tokenizer` 类或实现新的分块逻辑。

### 调整检索权重
修改 `_rrf_fusion` 中的融合逻辑，或改为加权求和。

## 性能优化建议

1. **HNSW 索引**: 数据导入后创建 `CREATE INDEX ... USING hnsw`
2. **批量嵌入**: `EMBEDDING_BATCH_SIZE=100` 减少 API 调用
3. **BM25 缓存**: 索引加载到内存，定期持久化
4. **连接池**: 配置 `pool_size=10, max_overflow=20`
5. **异步处理**: 文档处理放入任务队列 (Celery/RQ)

## 故障排查

### 嵌入维度不匹配
确保 `EMBEDDING_DIM` 与模型实际输出维度一致，且 pgvector 列定义匹配。

### 检索结果为空
1. 检查文档是否处理完成 (`status=completed`)
2. 检查 `document_chunks.embedding` 是否为 NULL
3. 检查租户隔离是否正确

### Cohere Rerank 失败
- 检查 `COHERE_API_KEY` 是否配置
- 查看日志中的错误详情
- 失败时自动回退到混合检索结果

## 许可证
MIT