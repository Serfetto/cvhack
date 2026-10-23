"""MinIO (S3): снапшоты, клипы. Бакет открыт на чтение анонимно, ключи содержат UUID события —
так <img>/<video> в браузере работают через шлюз /media/{bucket}/{key} без presigned-подписей."""

from __future__ import annotations

import asyncio
import io
import json

from minio import Minio
from minio.error import S3Error

from common.logging import get_logger

log = get_logger(__name__)


class Storage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False, public_base: str = "/media"):
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self.public_base = public_base.rstrip("/")

    @classmethod
    def from_settings(cls, s) -> Storage:
        return cls(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_bucket, s.minio_secure, s.media_public_base)

    async def ensure_bucket(self, attempts: int = 60) -> None:
        def _ensure():
            if not self.client.bucket_exists(self.bucket):
                try:
                    self.client.make_bucket(self.bucket)
                except S3Error as e:
                    if e.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                        raise
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket}/*"],
                    }
                ],
            }
            self.client.set_bucket_policy(self.bucket, json.dumps(policy))

        for i in range(attempts):
            try:
                await asyncio.to_thread(_ensure)
                return
            except Exception as e:
                if i == attempts - 1:
                    raise
                log.warning("minio_not_ready", error=str(e)[:200])
                await asyncio.sleep(1)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await asyncio.to_thread(self.client.put_object, self.bucket, key, io.BytesIO(data), len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            resp = self.client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(_get)

    def public_url(self, key: str | None) -> str | None:
        return f"{self.public_base}/{self.bucket}/{key}" if key else None
