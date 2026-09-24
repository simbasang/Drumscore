# Drumscore

Generate playable drum notation from a YouTube song and practise along with a
synchronized player. See `PROJECT.md` for the full product spec and MVP plan.

## Repository layout

```
drumscore/
├── frontend/   Next.js (TypeScript, App Router)
├── backend/    FastAPI (Python, managed with uv)
└── PROJECT.md  Product spec and MVP plan
```

## Prerequisites

- Node.js 20+ and [pnpm](https://pnpm.io/)
- Python 3.13+ and [uv](https://docs.astral.sh/uv/)

## Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. Health check: `GET /api/health`.

Drum transcription runs in an isolated Python 3.12 environment (DrumScript
requires `Python <3.13`, incompatible with the main backend's Python 3.13).
Set it up once:

```bash
cd backend/drumscript_runner
uv sync
```

The main backend invokes it as a subprocess — no need to run it separately.

Run tests:

```bash
cd backend
uv run pytest
```

## Frontend

```bash
cd frontend
cp .env.local.example .env.local
pnpm install
pnpm dev
```

The app runs at `http://localhost:3000` and reads the backend URL from
`NEXT_PUBLIC_API_URL` (see `.env.local.example`).

Run tests:

```bash
cd frontend
pnpm test
```

## Running locally

```bash
docker compose -f docker-compose.dev.yml up -d          # Postgres 18 on port 5432
cd backend && cp .env.example .env
uv run uvicorn app.main:app --reload                     # API (applies migrations on startup)
cd backend && uv run python -m app.worker                # workers (second terminal)
cd frontend && pnpm dev                                  # http://localhost:3000 (third terminal)
```

- Port 5432 must be free. If another Postgres already uses it, change the host port in
  `docker-compose.dev.yml` and the port in `DATABASE_URL` (`backend/.env`) together.
- Ctrl+C in the worker terminal stops gracefully: the stage in flight finishes or is
  abandoned, and the job goes back to the queue without using up an attempt
  (`docs/PERSISTENCE.md` §4).
- If you shorten `LEASE_SECONDS` (for example to test lease expiry), set
  `HEARTBEAT_SECONDS` below it as well; the settings refuse a heartbeat that is not
  shorter than the lease.

Tests: `cd backend && uv run pytest` (needs Docker; `-m "not integration"` skips Postgres tests) and `cd frontend && pnpm test`.

## Development order

The project is built incrementally, one MVP task from `PROJECT.md` at a time.
Do not skip ahead — see `CLAUDE.md` for the working method.
