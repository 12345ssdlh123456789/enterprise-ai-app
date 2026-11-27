from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


class DocumentBase(BaseModel):
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    file_hash: str


class DocumentCreate(DocumentBase):
    knowledge_base_id: Optional[UUID] = None
    meta: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )


class DocumentUpdate(BaseModel):
    filename: Optional[str] = None
    knowledge_base_id: Optional[UUID] = None
    meta: Optional[dict] = Field(
        None, validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata"
    )


class DocumentRead(DocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    knowledge_base_id: Optional[UUID]
    document_type: str
    storage_path: str
    status: str
    error_message: Optional[str]
    page_count: int
    chunk_count: int
    token_count: int
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime]


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    tenant_id: UUID
    version_number: int
    filename: str
    file_size: int
    file_hash: str
    storage_path: str
    change_summary: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime


class PresignedUploadUrlRequest(BaseModel):
    filename: str
    content_type: str
    file_size: int
    file_hash: str
    knowledge_base_id: Optional[UUID] = None


class PresignedUploadUrlResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int


class PresignedDownloadUrlRequest(BaseModel):
    object_key: str
    expires_in: int = 3600


class PresignedDownloadUrlResponse(BaseModel):
    download_url: str
    expires_in: int


class DocumentProcessRequest(BaseModel):
    # 路径里已有 doc_id，body 里这个是可选的（兼容旧调用）
    document_id: Optional[UUID] = None
    force_reprocess: bool = False


class DocumentProcessResponse(BaseModel):
    document_id: UUID
    status: str
    page_count: int
    chunk_count: int
    token_count: int
    processing_time_ms: float
    # 解析完成后是否已送入 rag-service 入库（False = 未配置 KB / 关了自动入库 / rag 不可用）
    rag_ingested: bool = False


class BatchUploadRequest(BaseModel):
    files: List[PresignedUploadUrlRequest]


class BatchUploadResponse(BaseModel):
    upload_urls: List[PresignedUploadUrlResponse]