"""Pure-ASGI middlewares for the API: a per-request log context with an
X-Request-ID and one `http_request` event per request, and a request body
size limit that also covers bodies streamed without Content-Length."""

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.exceptions import HTTPException

from app.observability.logging import log_context, log_event

logger = logging.getLogger(__name__)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[dict[str, Any]], Any]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    def __init__(self, app: Any, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self._monotonic = monotonic

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, b"x-request-id")
        request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        status = 500
        started = self._monotonic()

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode("latin-1"))]
                message = {**message, "headers": headers}
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("unhandled_error")
                raise
            finally:
                log_event(
                    logger, "http_request",
                    method=scope["method"], path=scope["path"], status=status,
                    duration_ms=round((self._monotonic() - started) * 1000),
                )


class _BodyTooLarge(HTTPException):
    """Raised by `limited_receive` while FastAPI streams the body. Subclassing
    HTTPException lets FastAPI's own body-parsing (`await request.body()` in
    fastapi/routing.py, which catches any other exception and turns it into a
    generic 400) recognise and re-raise it as-is via its `except HTTPException:
    raise`, so ExceptionMiddleware renders the real 413. The `except
    _BodyTooLarge` below still catches it for non-FastAPI ASGI apps that never
    look at exception type."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=f"Request body is larger than the {max_bytes}-byte limit")


class RequestSizeLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge(self.max_bytes)
            return message

        async def tracking_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": _BodyTooLarge(self.max_bytes).detail}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
