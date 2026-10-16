"""Presigned image uploads: the service with a fake signer, plus one offline botocore case."""

from urllib.parse import parse_qs, urlparse

import pytest

from app.services.media_uploads import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    PRESIGN_TTL_SECONDS,
    Boto3UploadSigner,
    InvalidUpload,
    MediaUploadService,
)

ACCOUNT = "0123456789abcdef0123456789abcdef"
PUBLIC = "https://media.example.com"


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def presign_put(
        self, *, key: str, content_type: str, size_bytes: int, expires_in: int
    ) -> str:
        self.calls.append(
            {
                "key": key,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "expires_in": expires_in,
            }
        )
        return f"https://signed.example.com/{key}?X-Amz-Signature=fake"


def service() -> tuple[MediaUploadService, FakeSigner]:
    signer = FakeSigner()
    return MediaUploadService(signer, PUBLIC + "/"), signer


@pytest.mark.parametrize(("content_type", "extension"), ALLOWED_IMAGE_TYPES.items())
def test_key_is_under_the_store_with_the_extension_of_the_content_type(
    content_type, extension
):
    svc, signer = service()

    upload = svc.presign_image("store-1", content_type, 1024)

    assert upload.key.startswith("stores/store-1/")
    assert upload.key.endswith(f".{extension}")
    assert upload.public_url == f"{PUBLIC}/{upload.key}"
    assert upload.method == "PUT"
    assert upload.headers == {"Content-Type": content_type}
    assert signer.calls[0]["expires_in"] == PRESIGN_TTL_SECONDS


def test_each_upload_gets_a_fresh_key():
    svc, _ = service()

    first = svc.presign_image("store-1", "image/png", 10)
    second = svc.presign_image("store-1", "image/png", 10)

    assert first.key != second.key


@pytest.mark.parametrize(
    "content_type", ["image/svg+xml", "image/gif", "text/html", "", "IMAGE/PNG"]
)
def test_disallowed_content_type_is_rejected_before_signing(content_type):
    svc, signer = service()

    with pytest.raises(InvalidUpload):
        svc.presign_image("store-1", content_type, 10)

    assert signer.calls == []


@pytest.mark.parametrize("size", [0, -1, MAX_IMAGE_BYTES + 1])
def test_disallowed_size_is_rejected_before_signing(size):
    svc, signer = service()

    with pytest.raises(InvalidUpload):
        svc.presign_image("store-1", "image/png", size)

    assert signer.calls == []


def test_exactly_the_maximum_size_is_accepted():
    svc, signer = service()

    svc.presign_image("store-1", "image/webp", MAX_IMAGE_BYTES)

    assert signer.calls[0]["size_bytes"] == MAX_IMAGE_BYTES


def test_real_signature_covers_content_type_and_length_and_targets_r2():
    signer = Boto3UploadSigner(
        account_id=ACCOUNT,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket="media",
    )
    svc = MediaUploadService(signer, PUBLIC)

    upload = svc.presign_image("store-1", "image/png", 2048)

    parsed = urlparse(upload.upload_url)
    query = parse_qs(parsed.query)
    signed = query["X-Amz-SignedHeaders"][0].split(";")
    assert parsed.hostname == f"{ACCOUNT}.r2.cloudflarestorage.com"
    assert parsed.path == f"/media/{upload.key}"
    assert "content-length" in signed
    assert "content-type" in signed
    assert query["X-Amz-Expires"] == [str(PRESIGN_TTL_SECONDS)]
    assert "test-secret-key" not in upload.upload_url


def test_signature_differs_when_the_signed_size_differs():
    signer = Boto3UploadSigner(
        account_id=ACCOUNT,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket="media",
    )

    def signature(size: int) -> str:
        url = signer.presign_put(
            key="stores/s/k.png",
            content_type="image/png",
            size_bytes=size,
            expires_in=60,
        )
        return parse_qs(urlparse(url).query)["X-Amz-Signature"][0]

    assert signature(100) != signature(101)


def test_signer_repr_does_not_expose_credentials():
    signer = Boto3UploadSigner(
        account_id=ACCOUNT,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket="media",
    )

    assert "test-secret-key" not in repr(signer)
