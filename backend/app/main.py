from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.config import get_settings
from app.observability.logging import configure_logging
from app.persistence.migrations import upgrade_to_head

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}
