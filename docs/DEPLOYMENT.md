# Deployment

How to build and run Drumscore in production: a single-host Docker Compose
stack (`deploy/docker-compose.yml`) of Postgres, a one-shot migration step,
the API, the workers and the frontend. `docs/OPERATIONS.md` documents every
backend setting, the log format and the limits; `docs/PERSISTENCE.md`
documents the job queue and artifact storage these containers share.

## 1. Services

| Service | Image | Role | Health |
|---|---|---|---|
| `postgres` | `postgres:18-alpine` | Projects, jobs, analyses, score versions, stage cache. | `pg_isready` |
| `migrate` | `drumscore-backend` | Applies Alembic migrations (`python -m app.persistence.migrations`), then exits. | exit code 0 |
| `api` | `drumscore-backend` | FastAPI (`uvicorn`, no `--reload`), port 8000. | `GET /api/ready` |
| `worker` | `drumscore-backend` | `python -m app.worker`: `WORKER_CONCURRENCY` worker processes. | `python -m app.readiness worker` |
| `frontend` | `drumscore-frontend` | Next.js standalone server, port 3000. | `GET /` |

Start order is enforced by `depends_on`: Postgres healthy → `migrate`
completed → `api` and `worker` → `frontend` once the API is healthy. The API
and workers therefore never run against an old schema, and
`RUN_MIGRATIONS_ON_STARTUP` is `false` inside the stack.

The backend image contains everything the pipeline needs: ffmpeg, Deno
(yt-dlp's JavaScript runtime) with `yt-dlp-ejs` (YouTube challenge solver
scripts, installed as a package instead of downloaded at runtime), the main
Python 3.13 environment, DrumScript's separate Python 3.12 environment, and
the Demucs `htdemucs` weights, baked in at build time (`HF_HOME`,
`HF_HUB_OFFLINE=1`). Workers download nothing at runtime except the songs
themselves. Torch is the CPU build on Linux (see `backend/pyproject.toml`),
so the backend image is ~5.6 GB (two ML environments of ~1.6 GB each)
instead of carrying several GB of CUDA libraries per environment; there is no GPU
image (TECHNICAL_DEBT.md).

## 2. Configuration

```bash
cp deploy/.env.example deploy/.env    # git-ignored; never commit it
```

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | — (required) | Postgres password; the stack builds the backend's `DATABASE_URL` from it. Compose refuses to start without it. |
| `PUBLIC_API_URL` | `http://localhost:8000` | API URL **as the browser sees it**. Passed to the frontend as `API_URL` and read per request, so the same frontend image works in any environment. |
| `PUBLIC_FRONTEND_URL` | `http://localhost:3000` | Frontend URL as the browser sees it; becomes the API's `CORS_ALLOWED_ORIGINS`. |
| `API_PORT` / `FRONTEND_PORT` | `8000` / `3000` | Host ports. |
| `WORKER_CONCURRENCY` | `2` | Worker processes (concurrent pipelines) in the worker container. |
| `LOG_LEVEL` | `INFO` | Backend log level. |
| `DRUMSCORE_VERSION` | `latest` | Tag given to the built images. |

Any other backend setting from `docs/OPERATIONS.md` §2 (limits, retention,
lease timing, ...) can be added to the `environment:` of the `x-backend`
block in `deploy/docker-compose.yml`. Secrets reach the containers only
through `deploy/.env`/the environment, never through the images.

## 3. Clean build and start

Prerequisites: Docker Engine with Compose v2, free disk for the images
(~6 GB) and build cache, plus room for artifacts (`STORAGE_MAX_BYTES`, default
100 GiB).

```bash
cp deploy/.env.example deploy/.env                      # set POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml build       # first build: several minutes
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps          # every service "healthy", migrate "Exited (0)"
curl http://localhost:8000/api/ready                    # {"status":"ready", ...}
```

Then open `PUBLIC_FRONTEND_URL`. Logs: `docker compose -f
deploy/docker-compose.yml logs -f api worker` (JSON lines, `docs/OPERATIONS.md` §5).

## 4. Liveness and readiness

- `GET /api/health` — liveness: the API process answers. No dependencies checked.
- `GET /api/ready` — readiness: 200 `{"status":"ready","checks":[...]}` when the
  database is reachable **and** migrated to head and the storage root is
  writable; otherwise 503 `{"status":"not_ready",...}` with the failing check.
  Check details are sanitized (no passwords or absolute paths).
- `python -m app.readiness worker` — the worker's readiness: the same checks
  plus the engines (ffmpeg on `PATH`, DrumScript environment present). Prints
  the same JSON and exits 0/1; `python -m app.readiness api` runs the API's set.

Stuck or dead workers are handled by job leases (`docs/PERSISTENCE.md` §4),
not by the healthcheck: an expired lease makes the job claimable again.

## 5. Persistent data

Everything that must survive a restart lives in two named volumes:

| Volume | Mounted at | Contents |
|---|---|---|
| `pgdata` | `/var/lib/postgresql` (postgres) | All database state. |
| `storage` | `/data` (api, worker) = `STORAGE_ROOT` | Source audio, stems, raw transcription diagnostics (`docs/PERSISTENCE.md` §6). |

Containers themselves are disposable: `docker compose down` followed by `up`
keeps all projects. `down -v` **deletes both volumes**, i.e. all data.

Back up both together (the database references files in `storage`):

```bash
docker compose -f deploy/docker-compose.yml exec postgres pg_dump -U drumscore -Fc drumscore > drumscore.dump
docker run --rm -v drumscore_storage:/data -v "$PWD":/backup alpine tar czf /backup/storage.tgz -C /data .
```

## 6. Upgrading

```bash
git pull
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d       # re-runs migrate, then recreates api/worker/frontend
```

Stopping a worker is graceful: on SIGTERM the stage in flight finishes (or is
abandoned) and the job is released back to the queue without using up an
attempt (`docs/PERSISTENCE.md` §4). The worker's `stop_grace_period` is 10
minutes because a Demucs stage on CPU can take minutes; after that Docker
kills it and the job is reclaimed when its lease expires (one attempt used).
`docker compose stop -t <seconds> worker` shortens the wait.

## 7. Scaling

More concurrent pipelines: raise `WORKER_CONCURRENCY`, or run more worker
containers (`up -d --scale worker=3`). Every worker must share the `storage`
volume and the database; the queue's `FOR UPDATE SKIP LOCKED` claims keep them
from running the same job. Run a single `api` replica unless the admission
limits' advisory race (TECHNICAL_DEBT.md) is acceptable. Demucs is the most
memory-hungry stage, so size host RAM per concurrent pipeline, not per
container; the admission limits in `docs/OPERATIONS.md` §4 bound disk and
queue growth.

## 8. Out of scope for v1.0

- **TLS and a reverse proxy**: the stack publishes plain HTTP ports. Put it
  behind a TLS-terminating proxy (and set the `PUBLIC_*` URLs to the proxy's
  HTTPS URLs) before exposing it beyond a private network.
- **Authentication**: none (TECHNICAL_DEBT.md, "No authentication"); rely on
  network-level access control.
- **GPU images**, multi-host/Kubernetes deployment, image registry
  publishing and CI builds.
