import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import main
from app.api.projects import router as projects_router
from app.observability.http import RequestContextMiddleware, RequestSizeLimitMiddleware
from app.observability.logging import current_context
from tests.fakes import FakeMonotonic, logged_events


def context_app(monotonic=None):
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"context": current_context()}

    app.add_middleware(RequestContextMiddleware, monotonic=monotonic or FakeMonotonic())
    return app


def test_request_id_is_generated_bound_and_returned():
    client = TestClient(context_app())

    response = client.get("/ping")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    assert response.json()["context"] == {"request_id": request_id}


def test_safe_incoming_request_id_is_reused():
    client = TestClient(context_app())

    response = client.get("/ping", headers={"X-Request-ID": "abc-123.DEF_4"})

    assert response.headers["x-request-id"] == "abc-123.DEF_4"


def test_unsafe_request_id_is_replaced():
    client = TestClient(context_app())

    for unsafe in ("a b", 'quote"d', "x" * 65, ""):
        response = client.get("/ping", headers={"X-Request-ID": unsafe})

        assert response.headers["x-request-id"] != unsafe
        assert len(response.headers["x-request-id"]) == 32


def test_every_request_logs_an_http_request_event(caplog):
    monotonic = FakeMonotonic()
    app = context_app(monotonic)

    @app.get("/slow")
    def slow():
        monotonic.advance(0.25)
        return {}

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.observability.http"):
        response = client.get("/slow")

    event = logged_events(caplog, "http_request")[0]
    assert event == {
        "request_id": response.headers["x-request-id"],
        "method": "GET",
        "path": "/slow",
        "status": 200,
        "duration_ms": 250,
    }


def size_limited_app(max_bytes):
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)
    return app


def test_body_within_the_limit_passes():
    client = TestClient(size_limited_app(10))

    response = client.post("/echo", content=b"x" * 10)

    assert response.json() == {"size": 10}


def test_declared_oversized_body_is_rejected_with_413():
    client = TestClient(size_limited_app(10))

    response = client.post("/echo", content=b"x" * 11)

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is larger than the 10-byte limit"}


def test_streamed_body_without_content_length_is_cut_off_at_the_limit():
    received = []

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            received.append(message)
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunks = [
        {"type": "http.request", "body": b"x" * 6, "more_body": True},
        {"type": "http.request", "body": b"x" * 6, "more_body": False},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/echo", "headers": []}

    asyncio.run(RequestSizeLimitMiddleware(downstream, max_bytes=10)(scope, receive, send))

    assert sent[0]["status"] == 413
    assert len(received) == 1


def real_router_app(max_bytes):
    app = FastAPI()
    app.include_router(projects_router)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)
    app.add_middleware(RequestContextMiddleware)
    return app


def test_streamed_oversized_body_through_real_routing_is_rejected_with_413():
    client = TestClient(real_router_app(max_bytes=10))

    def chunks():
        yield b'{"url": "'
        yield b"x" * 20
        yield b'"}'

    response = client.post("/api/projects", content=chunks())

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is larger than the 10-byte limit"}


def test_main_app_installs_both_middlewares():
    classes = [m.cls for m in main.app.user_middleware]

    assert RequestContextMiddleware in classes
    assert RequestSizeLimitMiddleware in classes
    assert classes.index(RequestContextMiddleware) < classes.index(RequestSizeLimitMiddleware)
