-- ============================================
-- Enterprise AI App - PostgreSQL 初始化
-- 仅负责安装扩展；表结构由各服务的 SQLAlchemy
-- 模型通过 create_all / Alembic 统一管理，
-- 避免两份 DDL 漂移。
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
