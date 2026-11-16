"""Uniform error envelope, request-id middleware and global exception handlers.

Every error response has the shape
    {"error": {"code": str, "message": str, "request_id": str}, "detail": <message>}
`detail` is kept (always a string) so older CLI / dashboard builds keep working.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("redline.api")

REQUEST_ID_HEADER = "X-Request-ID"

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "-"


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = _request_id(request)
    out = dict(headers or {})
    out[REQUEST_ID_HEADER] = rid
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "request_id": rid},
            "detail": message,
        },
        headers=out,
    )


def _format_validation(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        msg = err.get("msg", "invalid input")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "invalid request"


async def _validation_handler(request: Request, exc: RequestValidationError):
    return error_response(request, 422, "validation_error", _format_validation(exc))


async def _http_handler(request: Request, exc: StarletteHTTPException):
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(request, exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _integrity_handler(request: Request, exc: IntegrityError):
    # Do not leak SQL / constraint internals to the client; log them server-side.
    logger.warning("integrity error request_id=%s: %s", _request_id(request), exc.orig)
    return error_response(request, 409, "conflict", "the request conflicts with existing data")


async def _unhandled_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled exception request_id=%s %s %s",
        _request_id(request),
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return error_response(request, 500, "internal_error", "internal server error")


def install_error_handling(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(HTTPException, _http_handler)
    app.add_exception_handler(IntegrityError, _integrity_handler)
    app.add_exception_handler(Exception, _unhandled_handler)


class RequestIdMiddleware:
    """Pure ASGI middleware: honours a sane inbound X-Request-ID, else generates one.

    Pure ASGI (not BaseHTTPMiddleware) so it also wraps responses produced by the
    500 handler, which Starlette runs in ServerErrorMiddleware outside user middleware.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                cand = v.decode("latin-1").strip()
                if 0 < len(cand) <= 128 and cand.isprintable():
                    rid = cand
                break
        rid = rid or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)
