from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ids import simple_generate_unique_route_id
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware

# ADR-003: only the Next.js server calls this API, so no browser origin is allowed.
NO_BROWSER_ORIGINS: list[str] = []


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        generate_unique_id_function=simple_generate_unique_route_id,
        openapi_url=settings.OPENAPI_URL,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=NO_BROWSER_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestIdMiddleware)
    register_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
