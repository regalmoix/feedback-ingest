import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc

from feedback_ingest.domain.errors import NotFoundError, UnauthorizedError

log = logging.getLogger(__name__)
_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _respond(status: HTTPStatus) -> _Handler:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status)

    return handle


async def _storage_unavailable(request: Request, exc: Exception) -> JSONResponse:
    extra = {"source_id": request.path_params.get("source_id", "-")}
    log.error(
        "storage unavailable: %s %s", request.method, request.url.path, exc_info=exc, extra=extra
    )
    return JSONResponse(
        {"detail": "storage unavailable"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _respond(HTTPStatus.NOT_FOUND))
    app.add_exception_handler(UnauthorizedError, _respond(HTTPStatus.UNAUTHORIZED))
    for exc in (sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.TimeoutError):
        app.add_exception_handler(exc, _storage_unavailable)
