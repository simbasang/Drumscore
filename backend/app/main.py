from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.projects import router as projects_router
from app.config import get_settings
from app.observability.http import RequestContextMiddleware, RequestSizeLimitMiddleware
from app.observability.logging import configure_logging
from app.persistence.migrations import upgrade_to_head
from app.readiness import CheckResult, api_checks, report

_settings = get_settings()
configure_logging(_settings.log_level, _settings.log_format)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.run_migrations_on_startup:
        upgrade_to_head(settings.database_url.get_secret_value())
    yield


app = FastAPI(title="Drumscore API", lifespan=lifespan)
app.include_router(projects_router)

app.add_middleware(RequestSizeLimitMiddleware, max_bytes=_settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)


@app.get("/api/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}


def get_readiness_checks() -> list[CheckResult]:  # pragma: no cover - production wiring, overridden in tests
    return api_checks(get_settings())


@app.get("/api/ready")
def get_ready(checks: list[CheckResult] = Depends(get_readiness_checks)) -> JSONResponse:
    """Readiness (unlike /api/health's liveness): 503 until the database is
    reachable and migrated and the storage root is writable."""
    body = report(checks)
    return JSONResponse(body, status_code=200 if body["status"] == "ready" else 503)
