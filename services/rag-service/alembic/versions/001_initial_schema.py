"""Initial RAG schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-15 00:00:00.000000

"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector 扩展：空库里没有它，建 embedding 列会报 type "vector" does not exist。
    # 放在最前面，并保留 IF NOT EXISTS，方便对已经装过扩展的库重复执行。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create enums
    # create_type=False：类型由下面这行显式创建，建表时不要让 SQLAlchemy 再 CREATE TYPE 一次，
    # 否则 Postgres 会报 type "document_status" already exists（旧版本 baseline 就是死在这）。
    # 必须和模型保持一致：SQLAlchemy 的 Enum(DocumentStatus) 默认存「枚举名」大写，
    # 类型名取类名小写 documentstatus。旧 baseline 写的小写标签 + document_status 是错的。
    document_status = postgresql.ENUM(
        'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED',
        name='documentstatus',
        create_type=False,
    )
    document_status.create(op.get_bind(), checkfirst=True)

    # knowledge_bases table
    op.create_table(
        'knowledge_bases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('embedding_model', sa.String(100), nullable=False),
        sa.Column('embedding_dim', sa.Integer, nullable=False),
        sa.Column('chunk_size', sa.Integer, nullable=False, default=1000),
        sa.Column('chunk_overlap', sa.Integer, nullable=False, default=200),
        sa.Column('retrieval_top_k', sa.Integer, nullable=False, default=20),
        sa.Column('retrieval_final_k', sa.Integer, nullable=False, default=5),
        sa.Column('rrf_k', sa.Integer, nullable=False, default=60),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_knowledge_bases_tenant_id', 'knowledge_bases', ['tenant_id'])

    # documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('knowledge_base_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('original_filename', sa.String(512), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('file_size', sa.BigInteger, nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('status', document_status, nullable=False, default='PENDING'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('chunk_count', sa.Integer, nullable=False, default=0),
        sa.Column('token_count', sa.Integer, nullable=False, default=0),
        sa.Column('metadata', postgresql.JSONB, nullable=False, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_documents_knowledge_base_id', 'documents', ['knowledge_base_id'])
    op.create_index('ix_documents_tenant_id', 'documents', ['tenant_id'])
    op.create_index('ix_documents_status', 'documents', ['status'])
    op.create_index('ix_documents_file_hash', 'documents', ['file_hash'])
    op.create_unique_constraint('uq_documents_tenant_file_hash', 'documents', ['tenant_id', 'file_hash'])
    op.create_foreign_key('fk_documents_knowledge_base', 'documents', 'knowledge_bases', ['knowledge_base_id'], ['id'], ondelete='CASCADE')

    # document_chunks table
    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('knowledge_base_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chunk_index', sa.Integer, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('token_count', sa.Integer, nullable=False),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=False, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_document_chunks_knowledge_base_id', 'document_chunks', ['knowledge_base_id'])
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'])
    op.create_index('ix_document_chunks_tenant_id', 'document_chunks', ['tenant_id'])
    op.create_index('ix_document_chunks_chunk_index', 'document_chunks', ['document_id', 'chunk_index'])
    op.create_foreign_key('fk_document_chunks_knowledge_base', 'document_chunks', 'knowledge_bases', ['knowledge_base_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_document_chunks_document', 'document_chunks', 'documents', ['document_id'], ['id'], ondelete='CASCADE')

    # HNSW index for vector search (created after data is loaded for better performance)
    # op.execute('CREATE INDEX ix_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);')


def downgrade() -> None:
    op.drop_table('document_chunks')
    op.drop_table('documents')
    op.drop_table('knowledge_bases')
    document_status = postgresql.ENUM(
        'pending', 'processing', 'completed', 'failed',
        name='document_status',
        create_type=False,
    )
    document_status.drop(op.get_bind(), checkfirst=True)