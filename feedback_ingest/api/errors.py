from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from feedback_ingest.domain.errors import NotFoundError, UnauthorizedError

_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _respond(status: HTTPStatus, detail: str | None = None) -> _Handler:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": detail or str(exc)}, status_code=status)

    return handle


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _respond(HTTPStatus.NOT_FOUND))
    app.add_exception_handler(UnauthorizedError, _respond(HTTPStatus.UNAUTHORIZED))
    app.add_exception_handler(
        OperationalError, _respond(HTTPStatus.SERVICE_UNAVAILABLE, "storage unavailable")
    )
