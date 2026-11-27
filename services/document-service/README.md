# Document Service

企业级文档处理服务，支持多格式解析 (PDF、DOCX、TXT、Markdown、图片)、OCR 文字识别、MinIO 对象存储、预签名 URL 上传下载。

## 架构概览

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Upload     │────▶│   MinIO      │────▶│   Parser     │
│  (Presigned  │     │  (S3 API)    │     │  (PDF/DOCX/  │
│   URL)       │     │              │     │   TXT/MD/    │
└──────────────┘     └──────────────┘     │   Image/OCR) │
                                           └──────┬───────┘
                                                  │
                                           ┌──────▼───────┐
                                           │  PostgreSQL  │
                                           │  (Metadata)  │
                                           └──────────────┘
```

## 核心功能

### 1. 多格式解析
| 格式 | 解析库 | 特性 |
|------|--------|------|
| PDF | pdfplumber | 文本提取、表格、页码、坐标 |
| DOCX | python-docx | 段落、表格、样式 |
| TXT | 内置 | 多编码自动检测 (UTF-8/GBK/GB2312) |
| Markdown | markdown-it-py | 渲染为 HTML 再转纯文本 |
| 图片 (PNG/JPG/TIFF) | Tesseract OCR | 中英混合识别 (chi_sim+eng) |

### 2. 存储管理
- **MinIO** (S3 兼容) 对象存储
- **预签名 URL** 直传直下，减轻服务器压力
- **去重**: SHA256 哈希去重，同一文件仅存一份
- **版本控制**: 文档版本历史

### 3. 上传方式
- **预签名 URL** (推荐大文件): 客户端直传 MinIO
- **Multipart** (小文件): 直接上传到服务
- **批量预签名**: 一次获取多个上传 URL

### 4. 处理管线
```
UPLOADING → UPLOADED → PROCESSING → PROCESSED
                    ↓ (失败)
                   FAILED
```

## 快速开始

### 1. 安装依赖
```bash
cd services/document-service
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 配置 MinIO、数据库等
```

### 3. 启动 MinIO (开发环境)
```bash
docker run -d -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin123 \
  minio/minio server /data --console-address ":9001"
```

### 4. 运行迁移
```bash
alembic upgrade head
```

### 5. 启动服务
```bash
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8004
```

### 6. 上传文档 (预签名 URL 方式)
```bash
# 1. 获取预签名上传 URL
curl -X POST http://localhost:8004/api/v1/upload/presigned-url \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "doc.pdf",
    "content_type": "application/pdf",
    "file_size": 1024000,
    "file_hash": "sha256_hash_here"
  }'

# 2. 客户端 PUT 上传文件到返回的 upload_url
curl -X PUT -T doc.pdf "https://minio-url..."

# 3. 完成上传
curl -X POST http://localhost:8004/api/v1/upload/complete \
  -F "object_key=tenant/ab/hash.pdf" \
  -F "filename=doc.pdf" \
  -F "content_type=application/pdf" \
  -F "file_size=1024000" \
  -F "file_hash=sha256_hash_here"
```

### 7. 处理文档
```bash
curl -X POST http://localhost:8004/api/v1/documents/<doc_id>/process \
  -H "Content-Type: application/json" \
  -d '{"force_reprocess": false}'
```

### 8. 下载文档
```bash
# 获取预签名下载 URL
curl -X POST http://localhost:8004/api/v1/download/presigned-url \
  -H "Content-Type: application/json" \
  -d '{"object_key": "tenant/ab/hash.pdf", "expires_in": 3600}'

# 或直接下载
curl -O http://localhost:8004/api/v1/download/<doc_id>
```

## 配置说明

### MinIO 配置
```bash
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=documents
MINIO_USE_SSL=false
MINIO_REGION=us-east-1
```

### 文件限制
```bash
MAX_FILE_SIZE=104857600  # 100MB
ALLOWED_MIME_TYPES=application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,image/png,image/jpeg,image/tiff
```

### OCR 配置
```bash
TESSERACT_CMD=tesseract
TESSERACT_LANG=chi_sim+eng  # 中文简体 + 英文
```

## API 接口

| 模块 | 路径 | 功能 |
|------|------|------|
| Documents | `/api/v1/documents` | CRUD、列表、版本、统计 |
| Upload | `/api/v1/upload` | 预签名 URL、完成上传、Multipart |
| Download | `/api/v1/download` | 预签名下载、直接下载 |
| Process | `/api/v1/documents/{id}/process` | 解析处理 |

## 数据库模型

| 表 | 说明 |
|----|------|
| `documents` | 文档元数据 (哈希、存储路径、状态、页数、分块数) |
| `document_versions` | 文档版本历史 |

## 监控指标

- `documents_uploaded_total` - 上传总数
- `documents_processed_total` - 处理总数 (成功/失败)
- `document_processing_duration_seconds` - 处理延迟
- `document_file_size_bytes` - 文件大小分布
- `minio_upload_duration_seconds` - MinIO 上传延迟

## 部署

### Docker
```bash
docker build -f infra/docker/document-service/Dockerfile -t enterprise-ai/document-service .
docker run -p 8004:8004 --env-file .env enterprise-ai/document-service
```

### Docker Compose
```bash
docker-compose up document-service
```

## 开发指南

### 添加新解析器
在 `DocumentParser.parse()` 中添加新的 `elif` 分支，实现 `_parse_xxx` 方法。

### 自定义 OCR 语言
修改 `TESSERACT_LANG` 环境变量，如 `eng+chi_tra+ja`。

### 存储后端替换
实现新的 `StorageClient` 类，替换 `MinIOClient`。

## 故障排查

### PDF 解析为空
- 检查 PDF 是否为扫描件 (需 OCR)
- 尝试 `pdfplumber` 的 `extract_text(layout=True)`

### OCR 识别率低
- 确保安装了 `tesseract-ocr` 和语言包
- 图片预处理: 二值化、去噪、放大

### MinIO 连接失败
- 检查 `MINIO_ENDPOINT` 是否正确 (含端口)
- 检查网络策略 / 防火墙
- 验证 Access Key / Secret Key

### 预签名 URL 403
- 确保 MinIO 策略允许 PutObject/GetObject
- 检查 URL 是否过期 (默认 1 小时)

## 许可证
MIT