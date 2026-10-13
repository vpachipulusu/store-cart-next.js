import json
import logging

import pytest
from fastapi import APIRouter, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.main import create_app

router = APIRouter()


class Item(BaseModel):
    count: int


@router.get("/_test/forbidden", tags=["t"])
async def forbidden() -> None:
    raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/_test/boom", tags=["t"])
async def boom() -> None:
    raise RuntimeError("secret-internal-detail /srv/app/db.py")


@router.post("/_test/item", tags=["t"])
async def create_item(item: Item) -> Item:
    return item


app = create_app()
app.include_router(router)


@pytest.fixture
def client() -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_unknown_route_uses_envelope(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/nope")

    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "Not Found"}


async def test_http_exception_uses_envelope(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/_test/forbidden")

    assert response.status_code == 403
    assert response.json() == {"success": False, "error": "Forbidden"}


async def test_validation_error_uses_envelope_without_internals(
    client: AsyncClient,
) -> None:
    async with client:
        response = await client.post("/_test/item", json={"count": "x"})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


async def test_unhandled_error_hides_details_and_logs_them(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        async with client:
            response = await client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Internal server error"}
    assert "secret-internal-detail" not in response.text
    assert "Traceback" not in response.text
    assert any(r.exc_info for r in caplog.records)
    assert any(
        getattr(r, "request_id", None) == response.headers["x-request-id"]
        for r in caplog.records
    )


async def test_response_carries_a_request_id(client: AsyncClient) -> None:
    async with client:
        first = await client.get("/health")
        second = await client.get("/health")

    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_cors_allows_no_browser_origin(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health", headers={"Origin": "https://evil.test"})
        preflight = await client.options(
            "/health",
            headers={
                "Origin": "https://evil.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in preflight.headers


async def test_request_log_is_json_with_request_id(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.logging import configure_logging

    root = logging.getLogger()
    saved = root.handlers, root.level
    try:
        configure_logging("INFO")
        async with client:
            response = await client.get("/health")
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    finally:
        root.handlers, level = saved
        root.setLevel(level)

    records = [json.loads(ln) for ln in lines]
    request_logs = [r for r in records if r["message"] == "request completed"]
    assert request_logs
    assert request_logs[-1]["request_id"] == response.headers["x-request-id"]
    assert request_logs[-1]["status"] == 200
