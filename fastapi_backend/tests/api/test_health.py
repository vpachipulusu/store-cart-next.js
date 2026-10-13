from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_returns_ok() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_identifies_storecart() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "StoreCart API"
    assert schema["paths"]["/health"]["get"]["operationId"] == "health-health_check"
