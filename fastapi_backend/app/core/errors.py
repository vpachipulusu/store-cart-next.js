"""Error envelope: every error is {"success": false, "error": "<message>"}."""

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT

logger = logging.getLogger("storecart.errors")

INTERNAL_ERROR_MESSAGE = "Internal server error"
INVALID_REQUEST_MESSAGE = "Invalid request"


def error_response(
    status_code: int, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
        headers=headers,
    )


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Error"
    return error_response(exc.status_code, message, exc.headers)


async def validation_exception_handler(
    _request: Request, _exc: RequestValidationError
) -> JSONResponse:
    return error_response(HTTP_422_UNPROCESSABLE_CONTENT, INVALID_REQUEST_MESSAGE)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.scope.get("state", {}).get("request_id")
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"request_id": request_id},
    )
    headers = {"X-Request-ID": request_id} if request_id else None
    return error_response(500, INTERNAL_ERROR_MESSAGE, headers)


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)
