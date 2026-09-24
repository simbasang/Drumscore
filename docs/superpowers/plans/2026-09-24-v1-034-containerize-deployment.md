# V1-034 — Containerize and define production deployment (#85)

Goal: reproducible production containers for frontend, API and workers
(audio/ML deps included), readiness checks, explicit persistent storage, no
dev-reload assumptions, and a documented clean build/start.

## Findings (current code)

- `backend/app/main.py`: CORS origin hard-coded to `http://localhost:3000`;
  `/api/health` is liveness only (no DB/storage check).
- Frontend reads `NEXT_PUBLIC_API_URL` in server components of statically
  prerendered pages → value is frozen at **build** time; one image can't be
  pointed at a different API.
- Both `uv.lock` files resolve `torch` from PyPI → on Linux that pulls ~40
  `nvidia-*` CUDA wheels (multi-GB, twice: main venv + DrumScript runner venv).
- Demucs downloads `htdemucs` weights via torch.hub on first use (runtime
  network + non-reproducible). DrumScript with `full_song=False` loads no model
  files.
- DrumScript runner needs its own Python 3.12 venv at
  `backend/drumscript_runner/.venv` (path is derived in code).
- yt-dlp needs ffmpeg; dev machine also has `deno` (yt-dlp's JS runtime for
  YouTube challenges).
- Migrations run in the API lifespan (`RUN_MIGRATIONS_ON_STARTUP`); workers
  don't wait for them.

## Decisions (defaults — flag if you disagree)

1. Target: **single-host Docker Compose** (`deploy/docker-compose.yml`). No
   k8s, TLS/reverse proxy, auth or GPU — documented as out of scope/debt.
2. **CPU-only torch on Linux** via an explicit uv index scoped with
   `sys_platform == 'linux'`; Windows dev resolution unchanged.
3. Frontend API URL becomes **runtime** config (`API_URL`, server-only env,
   read per request) so one image serves any environment; `NEXT_PUBLIC_API_URL`
   kept as fallback for dev, then `http://localhost:8000`.
4. Migrations run in a one-shot `migrate` service; API/worker start only after
   it completes (`RUN_MIGRATIONS_ON_STARTUP=false` in compose).
5. Bake Demucs weights into the backend image (`TORCH_HOME=/opt/torch`).
6. yt-dlp-ejs is **not** added up front; the end-to-end container check decides
   (evidence first). `deno` is installed in the backend image to match dev.

## Tasks

### T1 — Readiness checks (backend, TDD)
Files: `backend/app/readiness.py`, `backend/tests/test_readiness.py`.
- `@dataclass(frozen=True) CheckResult(name: str, ok: bool, detail: str)`.
- `check_database(database_url: str) -> CheckResult`: connect, `SELECT 1`,
  compare Alembic current revision (`MigrationContext`) with script head
  (`ScriptDirectory` from `migrations._config`); not-at-head → not ok.
- `check_storage(root: Path) -> CheckResult`: root exists, is a dir, and a
  temp file can be created+deleted in it.
- `check_engines(runner_python: Path) -> CheckResult`: `ffmpeg` on PATH
  (`shutil.which`), DrumScript runner python exists.
- `api_checks(settings)` = database + storage; `worker_checks(settings)` = those
  + engines. `details` pass through `sanitize_error_message` (no secrets/paths).
- `main(argv)`: `python -m app.readiness [api|worker]` → prints JSON, exit 0/1
  (container healthcheck for the worker).
Tests:
- `test_check_storage_should_pass_for_writable_dir` / `_fail_for_missing_dir`
- `test_check_engines_should_fail_when_ffmpeg_missing` (monkeypatch `shutil.which`)
  / `_fail_when_runner_python_missing` / `_pass_when_both_present`
- `test_check_database_should_fail_for_unreachable_url` (bad port, short
  `connect_timeout`), detail has no password
- integration: `test_check_database_should_pass_at_head` /
  `_fail_before_migrations` (existing testcontainers fixture)
- `test_main_should_exit_nonzero_when_a_check_fails` (monkeypatched checks)

### T2 — `/api/ready` + configurable CORS (TDD)
Files: `backend/app/main.py`, `backend/app/config.py`, `backend/.env.example`,
`backend/tests/test_health.py`, `backend/tests/test_config.py`, `test_main.py`.
- `GET /api/ready` → 200 `{"status":"ready","checks":[...]}` or 503
  `{"status":"not_ready",...}`; checks provider is a FastAPI dependency
  (`get_readiness_checks`, overridden in tests).
- Setting `cors_allowed_origins: list[str] = ["http://localhost:3000"]`
  (env `CORS_ALLOWED_ORIGINS`, JSON list or comma-separated via validator).
Tests: ready 200 when all ok / 503 when one fails; CORS header echoes a
configured origin and not an unconfigured one; settings parse comma list.
`test_every_setting_is_documented_in_operations_md` forces the doc row.

### T3 — Migration entrypoint
`backend/app/persistence/migrations.py`: `if __name__ == "__main__"` →
`upgrade_to_head(get_settings().database_url.get_secret_value())`
(`# pragma: no cover - process entrypoint`, matching `app/worker/__main__.py`).

### T4 — Frontend runtime API URL (TDD)
Files: `frontend/lib/apiBaseUrl.ts` (+ `__tests__`), `app/page.tsx`,
`app/projects/[id]/page.tsx`, their tests, `.env.local.example`,
`next.config.ts` (`output: "standalone"`).
- `getApiBaseUrl(): string` → `API_URL ?? NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`.
- Pages `await connection()` (next/server) before reading it → rendered per
  request, never frozen at build. Pages become async; tests `render(await Home())`
  with `next/server` `connection` mocked via `frontend/__mocks__`.
Tests: `getApiBaseUrl` precedence (3 cases); page passes `API_URL` value to
children.

### T5 — CPU torch for Linux
`backend/pyproject.toml` and `backend/drumscript_runner/pyproject.toml`:
`[[tool.uv.index]] name="pytorch-cpu" url="https://download.pytorch.org/whl/cpu" explicit=true`
and `[tool.uv.sources] torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]`
(same for `torchaudio` if locked). `uv lock` both. Verify: Windows resolution
still PyPI torch same version; no `nvidia-*` for linux markers; full backend
suite green.

### T6 — Images
- `backend/Dockerfile` (multi-stage): base `python:3.13-slim` + `ffmpeg` +
  `deno` + uv (copied from `ghcr.io/astral-sh/uv`, latest stable tag verified at
  implementation). `uv sync --frozen --no-dev` for app and
  `uv sync --frozen` in `drumscript_runner` (uv-managed Python 3.12,
  `UV_PYTHON_INSTALL_DIR` inside the image). Pre-download `htdemucs`.
  Non-root user, `STORAGE_ROOT=/data`, `LOG_FORMAT=json`, `EXPOSE 8000`,
  `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log`
  (no `--reload`). `backend/.dockerignore` (`.venv`, `data`, `.env`, tests caches).
- `frontend/Dockerfile`: `node:24-slim` (current LTS; verify), corepack pnpm,
  `pnpm install --frozen-lockfile`, `next build`, runtime stage copies
  `.next/standalone` + static + public, non-root, `CMD node server.js`,
  `HOSTNAME=0.0.0.0`. `frontend/.dockerignore`.

### T7 — Compose + docs
- `deploy/docker-compose.yml`: `postgres` (pg 18, `pg_isready` healthcheck, no
  host port, volume `pgdata`), `migrate` (backend image, one-shot),
  `api` (healthcheck `/api/ready`, `RUN_MIGRATIONS_ON_STARTUP=false`,
  `depends_on: migrate: service_completed_successfully`), `worker`
  (`python -m app.worker`, healthcheck `python -m app.readiness worker`,
  `init: true`, `stop_grace_period`), `frontend` (`API_URL`). Named volume
  `storage` at `/data` shared by api+worker. Host ports `${API_PORT:-8000}`,
  `${FRONTEND_PORT:-3000}`. `POSTGRES_PASSWORD` required (`${...:?}`).
  `restart: unless-stopped`. `deploy/.env.example`; `deploy/.env` git-ignored.
- `docs/DEPLOYMENT.md`: prerequisites, clean build/start, config, readiness vs
  liveness, persistent data + backup, upgrade (pull/build → migrate → up),
  scaling workers, out of scope (TLS, auth, GPU, multi-host).
- Update `docs/OPERATIONS.md` (new setting, readiness, §3 secrets mechanism =
  compose env file), `README.md` (pointer), `ARCHITECTURE_V1.md` (one line),
  `TECHNICAL_DEBT.md` (new entries: no GPU image; no TLS/reverse proxy).
- Test: `test_operations_doc`-style check that `deploy/.env.example` only uses
  compose-known variables is overkill — skip; compose validity checked by
  `docker compose config`.

## Verification (before PR)
- Backend `uv run pytest -q --tb=short`, frontend `npx jest --silent
  --reporters=summary`, lint + `tsc --noEmit`.
- `docker compose -f deploy/docker-compose.yml build` from clean, `up -d`;
  all services healthy; `/api/ready` 200; stop postgres → `/api/ready` 503.
- Real job end to end in containers (submit YouTube URL → completed → score
  renders in browser via Playwright); restart worker mid-job → resumes.
- `down` + `up` → project still listed (volumes persist).

## Scope-outs
TLS/reverse proxy, auth (existing debt), GPU images, registry publishing/CI,
multi-host/k8s, release gate (#86).
