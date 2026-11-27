"""文档解析与分块。

本地部署没有 document-service 时，由网关直接完成"文件 -> 文本 -> 分块"，
这样知识库检索（/retrieval/search）才能拿到真实内容。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Iterable, List

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk, DocumentStatus, KnowledgeBase

TEXT_EXTS = {"txt", "md", "markdown", "csv", "json", "html", "htm", "log"}
SUPPORTED_EXTS = TEXT_EXTS | {"pdf", "docx"}


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def extract_text(path: str, ext: str) -> str:
    """从文件里抽取纯文本，不支持的格式抛 ValueError。"""
    ext = (ext or "").lower().lstrip(".")

    if ext in TEXT_EXTS - {"json", "html", "htm"}:
        return _read_text_file(path)

    if ext == "json":
        raw = _read_text_file(path)
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return raw

    if ext in {"html", "htm"}:
        raw = _read_text_file(path)
        try:
            from bs4 import BeautifulSoup  # type: ignore

            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text("\n")
        except ImportError:
            return re.sub(r"<[^>]+>", " ", raw)

    if ext == "pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
            raise ValueError("缺少 pypdf 依赖，无法解析 PDF") from exc

        reader = PdfReader(path)
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    if ext == "docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ValueError("缺少 python-docx 依赖，无法解析 DOCX") from exc

        document = docx.Document(path)
        return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())

    raise ValueError(f"暂不支持解析 {ext or '未知'} 格式的文档")


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """按段落聚合成块，超长段落滑动切分。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    chunk_size = max(200, chunk_size or 1000)
    overlap = max(0, min(overlap or 0, chunk_size // 2))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    buffer = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            step = chunk_size - overlap
            for start in range(0, len(paragraph), step):
                piece = paragraph[start:start + chunk_size]
                if piece.strip():
                    chunks.append(piece)
            continue

        if buffer and len(buffer) + len(paragraph) + 2 > chunk_size:
            chunks.append(buffer)
            buffer = (buffer[-overlap:] + "\n\n" + paragraph) if overlap else paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph

    if buffer:
        chunks.append(buffer)

    # 去掉纯空白块
    return [c for c in (chunk.strip() for chunk in chunks) if c]


def _count_tokens(text: str) -> int:
    return max(1, len(re.findall(r"\w+", text)))


def tokenize(text: str) -> Iterable[str]:
    """英文按词、中文按二字切片，用于轻量关键词检索。"""
    lowered = (text or "").lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    grams: List[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return words + grams


async def ingest_document(
    db: AsyncSession,
    doc: Document,
    kb: KnowledgeBase | None = None,
) -> int:
    """解析文档并写入分块，返回分块数量。"""
    meta = dict(doc.meta or {})
    path = meta.get("file_path")
    if not path or not os.path.exists(path):
        raise ValueError("找不到原始文件，无法解析该文档")

    ext = str(meta.get("file_ext") or os.path.splitext(path)[1].lstrip(".")).lower()
    text = extract_text(path, ext)
    chunk_size = getattr(kb, "chunk_size", None) or 1000
    overlap = getattr(kb, "chunk_overlap", None) or 200
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        raise ValueError("文档内容为空，未生成任何分块")

    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))

    total_tokens = 0
    for index, content in enumerate(chunks):
        tokens = _count_tokens(content)
        total_tokens += tokens
        db.add(
            DocumentChunk(
                document_id=doc.id,
                knowledge_base_id=doc.knowledge_base_id,
                content=content,
                token_count=tokens,
                sequence=index,
                meta={"chunk_index": index, "source": doc.file_name or doc.title},
            )
        )

    doc.status = DocumentStatus.COMPLETED
    doc.error_message = None
    doc.chunk_count = len(chunks)
    doc.token_count = total_tokens
    doc.processed_at = datetime.now(timezone.utc)
    doc.meta = {
        **meta,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "char_count": len(text),
    }

    # 重新计算知识库文档/分块计数，保持 /knowledge-bases/{id}/stats 接口准确
    if kb is not None:
        doc_cnt = await db.execute(
            select(func.count(Document.id)).where(
                Document.knowledge_base_id == doc.knowledge_base_id,
                Document.deleted_at.is_(None),
            )
        )
        kb.document_count = doc_cnt.scalar() or 0
        chunk_cnt = await db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.knowledge_base_id == doc.knowledge_base_id
            )
        )
        kb.chunk_count = chunk_cnt.scalar() or 0

    await db.flush()
    return len(chunks)
