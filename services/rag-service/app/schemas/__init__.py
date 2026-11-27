from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


class KnowledgeBaseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dim: int = Field(default=1536, gt=0)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    retrieval_top_k: int = Field(default=20, gt=0)
    retrieval_final_k: int = Field(default=5, gt=0)
    rrf_k: int = Field(default=60, gt=0)


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    chunk_size: Optional[int] = Field(None, gt=0)
    chunk_overlap: Optional[int] = Field(None, ge=0)
    retrieval_top_k: Optional[int] = Field(None, gt=0)
    retrieval_final_k: Optional[int] = Field(None, gt=0)
    rrf_k: Optional[int] = Field(None, gt=0)


class KnowledgeBaseRead(KnowledgeBaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


class DocumentBase(BaseModel):
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    file_hash: str


class DocumentCreate(DocumentBase):
    knowledge_base_id: UUID
    # 上游已解析好的正文放这里（被 chunk/embed 使用）；不传则用占位文本
    meta: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )


class DocumentRead(DocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    tenant_id: UUID
    status: str
    error_message: Optional[str]
    chunk_count: int
    token_count: int
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    tenant_id: UUID
    chunk_index: int
    content: str
    token_count: int
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    created_at: datetime


# Retrieval Schemas
class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    knowledge_base_id: UUID
    top_k: Optional[int] = Field(None, gt=0, le=50)
    use_rerank: bool = True
    filters: Optional[dict[str, Any]] = None


class RetrievedChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_filename: str
    content: str
    score: float
    metadata: dict


class RetrievalResponse(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    total_found: int
    retrieval_time_ms: float
    rerank_time_ms: Optional[float] = None
    # embedding 不可用时降级为纯 BM25 检索，用这两个字段告诉调用方「结果不完整」
    degraded: bool = False
    degraded_reason: Optional[str] = None


# 一站式入库：登记 + 分块 + 嵌入，避免调用方手工建 rag 文档再 process
class IngestRequest(BaseModel):
    knowledge_base_id: UUID
    title: str = Field(..., min_length=1, max_length=512)
    text: str = Field(..., min_length=1, description="已解析好的正文")
    file_hash: Optional[str] = Field(default=None, max_length=64)
    metadata: dict = Field(default_factory=dict)
    force_reprocess: bool = False


class IngestResponse(BaseModel):
    document_id: UUID
    knowledge_base_id: UUID
    status: str
    chunks_created: int
    processing_time_ms: float
    reused_existing: bool = False


# Embedding Schemas
class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=100)
    model: Optional[str] = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    usage: dict


# Batch Processing
class ProcessDocumentRequest(BaseModel):
    document_id: UUID
    force_reprocess: bool = False


class ProcessDocumentResponse(BaseModel):
    document_id: UUID
    status: str
    chunks_created: int
    processing_time_ms: float