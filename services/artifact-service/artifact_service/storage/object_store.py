"""Thin async wrapper over an S3-compatible object store (MinIO in Phase 0).

The bucket is private and every download goes through a short-lived signed URL — spec
§23 "object storage private / signed artifact download URLs / no public buckets".
"""
from __future__ import annotations

from dataclasses import dataclass

import aioboto3


@dataclass
class ObjectStoreConfig:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    signed_url_ttl_seconds: int = 300


class ObjectStore:
    def __init__(self, config: ObjectStoreConfig):
        self._config = config
        self._session = aioboto3.Session()

    def _client_ctx(self):
        c = self._config
        return self._session.client(
            "s3",
            endpoint_url=c.endpoint_url,
            aws_access_key_id=c.access_key,
            aws_secret_access_key=c.secret_key,
            region_name=c.region,
        )

    async def put_object(self, key: str, body: bytes, content_type: str) -> str:
        async with self._client_ctx() as client:
            await client.put_object(
                Bucket=self._config.bucket, Key=key, Body=body, ContentType=content_type
            )
        return f"s3://{self._config.bucket}/{key}"

    async def get_object(self, key: str) -> bytes:
        async with self._client_ctx() as client:
            response = await client.get_object(Bucket=self._config.bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()

    async def generate_presigned_download_url(self, key: str) -> str:
        async with self._client_ctx() as client:
            return await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._config.bucket, "Key": key},
                ExpiresIn=self._config.signed_url_ttl_seconds,
            )
