"""Presigned image uploads to Cloudflare R2 (KAN-66). No FastAPI imports.

R2 has no presigned POST policies, so the client PUTs the file to a presigned URL whose
signature covers ``Content-Type`` and ``Content-Length``: a different type or size fails
the signature check at R2. The object key is built here and never from client input.
The presigned URL carries a credential in its query string: never log it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Literal, Protocol

from app.core.ids import new_id

MAX_IMAGE_BYTES = 10 * 1024 * 1024
PRESIGN_TTL_SECONDS = 300
# SVG is deliberately absent: it can carry script.
ImageContentType = Literal["image/jpeg", "image/png", "image/webp"]
ALLOWED_IMAGE_TYPES = MappingProxyType(
    {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
)


class InvalidUpload(Exception):
    """The declared content type or size is not allowed."""


class UploadSigner(Protocol):
    def presign_put(
        self, *, key: str, content_type: str, size_bytes: int, expires_in: int
    ) -> str: ...


@dataclass(frozen=True)
class PresignedUpload:
    upload_url: str
    method: str
    headers: dict[str, str]
    key: str
    public_url: str
    expires_at: datetime


class Boto3UploadSigner:
    """Signs locally with botocore (no network call) against the R2 S3 endpoint."""

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
    ) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_put(
        self, *, key: str, content_type: str, size_bytes: int, expires_in: int
    ) -> str:
        url: str = self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size_bytes,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
        return url


class MediaUploadService:
    def __init__(self, signer: UploadSigner, public_base_url: str) -> None:
        self._signer = signer
        self._public_base_url = public_base_url.rstrip("/")

    def presign_image(
        self, store_id: str, content_type: str, size_bytes: int
    ) -> PresignedUpload:
        extension = ALLOWED_IMAGE_TYPES.get(content_type)
        if extension is None:
            raise InvalidUpload("Unsupported image type")
        if size_bytes <= 0 or size_bytes > MAX_IMAGE_BYTES:
            raise InvalidUpload("Image size is not allowed")
        key = f"stores/{store_id}/{new_id()}.{extension}"
        url = self._signer.presign_put(
            key=key,
            content_type=content_type,
            size_bytes=size_bytes,
            expires_in=PRESIGN_TTL_SECONDS,
        )
        return PresignedUpload(
            upload_url=url,
            method="PUT",
            headers={"Content-Type": content_type},
            key=key,
            public_url=f"{self._public_base_url}/{key}",
            expires_at=datetime.now(UTC) + timedelta(seconds=PRESIGN_TTL_SECONDS),
        )
