"""对象存储抽象：MinIO（S3 兼容）或本地文件系统。

本地开发没有 MinIO 时用 `STORAGE_PROVIDER=local`，两个后端对外接口一致
（upload / download / delete / presigned_upload_url / presigned_download_url），
所以上传、下载、解析链路在两种模式下走同一份业务代码。

local 模式的 presigned URL 指向本服务自己的 `/api/v1/storage/{object_key}`，
客户端 PUT 文件到该地址即可（与 MinIO 的 presigned PUT 用法一致）。
"""

import io
from pathlib import Path
from typing import Union

from app.core.config import settings

S3_PREFIX = "s3://"
LOCAL_PREFIX = "local://"


def object_key_from_path(storage_path: str) -> str:
    """把存进数据库的 storage_path 还原成 object key（兼容 s3://bucket/ 与 local://）。"""
    if storage_path.startswith(S3_PREFIX):
        rest = storage_path[len(S3_PREFIX) :]
        return rest.split("/", 1)[1] if "/" in rest else rest
    if storage_path.startswith(LOCAL_PREFIX):
        return storage_path[len(LOCAL_PREFIX) :]
    return storage_path


class MinIOClient:
    """MinIO 后端（S3 兼容）。"""

    def __init__(self):
        from minio import Minio

        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_USE_SSL,
            region=settings.MINIO_REGION,
        )
        self.bucket = settings.MINIO_BUCKET
        # 不在构造时连 MinIO：导入模块 / 启动服务不应该依赖对象存储可达，
        # 否则本地没有 MinIO 时连 Swagger 都打不开。首次真正读写时再建桶。
        self._bucket_ready = False

    def _ensure_bucket(self):
        if self._bucket_ready:
            return
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self._bucket_ready = True

    def upload(self, object_key: str, file_data: bytes, content_type: str) -> str:
        self._ensure_bucket()
        key = object_key_from_path(object_key)
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    def download(self, object_key: str) -> bytes:
        self._ensure_bucket()
        response = self.client.get_object(self.bucket, object_key_from_path(object_key))
        data = response.read()
        response.close()
        response.release_conn()
        return data

    def delete(self, object_key: str) -> None:
        self._ensure_bucket()
        self.client.remove_object(self.bucket, object_key_from_path(object_key))

    def describe_path(self, object_key: str) -> str:
        """存进数据库的 storage_path 表示。"""
        return f"s3://{self.bucket}/{object_key_from_path(object_key)}"

    def presigned_upload_url(self, object_key: str, expires_in: int = 3600) -> str:
        from datetime import timedelta

        self._ensure_bucket()
        return self.client.presigned_put_object(
            self.bucket, object_key_from_path(object_key), expires=timedelta(seconds=expires_in)
        )

    def presigned_download_url(self, object_key: str, expires_in: int = 3600) -> str:
        from datetime import timedelta

        self._ensure_bucket()
        return self.client.presigned_get_object(
            self.bucket, object_key_from_path(object_key), expires=timedelta(seconds=expires_in)
        )


class LocalStorageClient:
    """本地目录后端：文件落在 STORAGE_LOCAL_DIR 下，适合没有 MinIO 的本地开发/测试。"""

    def __init__(self):
        self.root = Path(settings.STORAGE_LOCAL_DIR).resolve()

    def _path(self, object_key: str) -> Path:
        key = object_key_from_path(object_key)
        target = (self.root / key).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"非法的 object key（越出存储根目录）：{object_key}")
        return target

    def upload(self, object_key: str, file_data: bytes, content_type: str) -> str:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_data)
        return f"{LOCAL_PREFIX}{object_key_from_path(object_key)}"

    def download(self, object_key: str) -> bytes:
        path = self._path(object_key)
        if not path.exists():
            raise FileNotFoundError(f"对象不存在：{object_key}")
        return path.read_bytes()

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)

    def describe_path(self, object_key: str) -> str:
        """存进数据库的 storage_path 表示。"""
        return f"{LOCAL_PREFIX}{object_key_from_path(object_key)}"

    def presigned_upload_url(self, object_key: str, expires_in: int = 3600) -> str:
        key = object_key_from_path(object_key)
        return f"{settings.PUBLIC_BASE_URL}/api/v1/storage/{key}"

    def presigned_download_url(self, object_key: str, expires_in: int = 3600) -> str:
        key = object_key_from_path(object_key)
        return f"{settings.PUBLIC_BASE_URL}/api/v1/storage/{key}"


def get_storage_client() -> Union[MinIOClient, LocalStorageClient]:
    """按 STORAGE_PROVIDER 返回存储后端（默认 minio）。"""
    if settings.STORAGE_PROVIDER.lower() == "local":
        return LocalStorageClient()
    return MinIOClient()
