from fastapi import FastAPI

from app.api.ids import simple_generate_unique_route_id
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import ERROR_RESPONSES, register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        generate_unique_id_function=simple_generate_unique_route_id,
        openapi_url=settings.OPENAPI_URL,
        responses=ERROR_RESPONSES,
    )

    # No CORSMiddleware on purpose (ADR-003): only the Next.js server calls this
    # API, so no browser origin is ever allowed.
    application.add_middleware(RequestIdMiddleware)
    register_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
