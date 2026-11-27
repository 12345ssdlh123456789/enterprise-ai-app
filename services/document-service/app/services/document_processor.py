import hashlib
import io
from typing import Optional, Tuple
from uuid import UUID

import pdfplumber
from docx import Document as DocxDocument
from PIL import Image
import pytesseract
import markdown

from app.core.config import settings
from app.models import Document, DocumentStatus, DocumentType
from app.services.storage import get_storage_client, object_key_from_path

import structlog
logger = structlog.get_logger()


class DocumentParser:
    """Parse various document formats and extract text content."""

    @staticmethod
    def detect_type(filename: str, content_type: str) -> DocumentType:
        """Detect document type from filename and MIME type."""
        ext = filename.lower().split(".")[-1] if "." in filename else ""

        if ext == "pdf" or content_type == "application/pdf":
            return DocumentType.PDF
        elif ext == "docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return DocumentType.DOCX
        elif ext in ("txt", "text") or content_type == "text/plain":
            return DocumentType.TXT
        elif ext in ("md", "markdown") or content_type == "text/markdown":
            return DocumentType.MARKDOWN
        elif ext in ("png", "jpg", "jpeg", "tiff", "bmp") or content_type.startswith("image/"):
            return DocumentType.IMAGE
        else:
            return DocumentType.OTHER

    @classmethod
    def parse(cls, file_data: bytes, doc: Document) -> Tuple[str, int, dict]:
        """
        Parse document and return (text_content, page_count, metadata).
        """
        doc_type = doc.document_type

        if doc_type == DocumentType.PDF:
            return cls._parse_pdf(file_data)
        elif doc_type == DocumentType.DOCX:
            return cls._parse_docx(file_data)
        elif doc_type == DocumentType.TXT:
            return cls._parse_txt(file_data)
        elif doc_type == DocumentType.MARKDOWN:
            return cls._parse_markdown(file_data)
        elif doc_type == DocumentType.IMAGE:
            return cls._parse_image(file_data)
        else:
            raise ValueError(f"Unsupported document type: {doc_type}")

    @staticmethod
    def _parse_pdf(file_data: bytes) -> Tuple[str, int, dict]:
        """Extract text from PDF using pdfplumber."""
        text_parts = []
        metadata = {"pages": []}

        with pdfplumber.open(io.BytesIO(file_data)) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                metadata["pages"].append({
                    "page_number": i + 1,
                    "width": page.width,
                    "height": page.height,
                    "chars": len(page_text),
                })

        full_text = "\n\n".join(text_parts)
        return full_text, page_count, metadata

    @staticmethod
    def _parse_docx(file_data: bytes) -> Tuple[str, int, dict]:
        """Extract text from DOCX."""
        doc = DocxDocument(io.BytesIO(file_data))
        text_parts = []

        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)

        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    text_parts.append(row_text)

        full_text = "\n\n".join(text_parts)
        # Estimate page count (rough)
        page_count = max(1, len(full_text) // 3000)

        return full_text, page_count, {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables)}

    @staticmethod
    def _parse_txt(file_data: bytes) -> Tuple[str, int, dict]:
        """Extract text from plain text file."""
        # Try multiple encodings
        for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                text = file_data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = file_data.decode("utf-8", errors="replace")

        page_count = max(1, len(text) // 3000)
        return text, page_count, {"encoding": encoding}

    @staticmethod
    def _parse_markdown(file_data: bytes) -> Tuple[str, int, dict]:
        """Extract text from Markdown."""
        for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                md_text = file_data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            md_text = file_data.decode("utf-8", errors="replace")

        # Convert to plain text (strip markdown syntax)
        html = markdown.markdown(md_text)
        # Simple HTML to text conversion
        import re
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\n\s*\n", "\n\n", text)

        page_count = max(1, len(text) // 3000)
        return text, page_count, {"original_markdown": True}

    @staticmethod
    def _parse_image(file_data: bytes) -> Tuple[str, int, dict]:
        """Extract text from image using OCR (Tesseract)."""
        try:
            image = Image.open(io.BytesIO(file_data))
            # Convert to RGB if needed
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Run OCR
            text = pytesseract.image_to_string(image, lang=settings.TESSERACT_LANG)

            metadata = {
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
                "ocr_lang": settings.TESSERACT_LANG,
            }

            return text.strip(), 1, metadata
        except Exception as e:
            logger.warning("OCR failed", error=str(e))
            return "", 1, {"ocr_error": str(e)}


class DocumentProcessor:
    """Process documents: store, parse, and prepare for RAG."""

    def __init__(self):
        self.parser = DocumentParser()
        self.storage = get_storage_client()

    def _generate_object_key(self, tenant_id: UUID, file_hash: str, filename: str) -> str:
        """Generate MinIO object key."""
        ext = filename.split(".")[-1] if "." in filename else "bin"
        return f"{tenant_id}/{file_hash[:2]}/{file_hash}.{ext}"

    def _compute_hash(self, file_data: bytes) -> str:
        """Compute SHA256 hash of file."""
        return hashlib.sha256(file_data).hexdigest()

    async def process_upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        tenant_id: UUID,
        knowledge_base_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
    ) -> Document:
        """Process uploaded file: store, parse, create document record."""
        file_hash = self._compute_hash(file_data)
        file_size = len(file_data)

        # Check if duplicate exists
        # (would query DB here - placeholder)

        # Generate object key and upload to MinIO
        object_key = self._generate_object_key(tenant_id, file_hash, filename)
        storage_path = self.storage.upload(object_key, file_data, content_type)

        # Detect document type
        doc_type = self.parser.detect_type(filename, content_type)

        # Create document record (status: UPLOADED)
        doc = Document(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            filename=filename,
            original_filename=filename,
            content_type=content_type,
            document_type=doc_type,
            file_size=file_size,
            file_hash=file_hash,
            storage_path=storage_path,
            status=DocumentStatus.UPLOADED,
            meta=metadata or {},
        )

        return doc

    async def process_document(self, doc: Document) -> dict:
        """Parse document content and update record."""
        import time
        start = time.perf_counter()

        try:
            doc.status = DocumentStatus.PROCESSING

            # Download from MinIO
            object_key = object_key_from_path(doc.storage_path)
            file_data = self.storage.download(object_key)

            # Parse
            text_content, page_count, parse_metadata = self.parser.parse(file_data, doc)

            # Update document
            doc.status = DocumentStatus.PROCESSED
            doc.page_count = page_count
            doc.processed_at = datetime.utcnow()
            # 注意：JSON 列必须整体赋值，原地 doc.meta.update(...) 不会被 SQLAlchemy 标记为脏数据
            meta = dict(doc.meta or {})
            meta.update(parse_metadata)
            # 解析出的正文一并存进 metadata.text：下游（rag-service 的
            # POST /documents/{id}/process）直接用它分块/嵌入，不必再解析一遍文件。
            if text_content:
                meta["text"] = text_content
            doc.meta = meta

            processing_time_ms = (time.perf_counter() - start) * 1000

            return {
                "status": "processed",
                "text_content": text_content,
                "page_count": page_count,
                "metadata": parse_metadata,
                "processing_time_ms": processing_time_ms,
            }

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            logger.error("Document processing failed", document_id=str(doc.id), error=str(e))
            raise


from datetime import datetime