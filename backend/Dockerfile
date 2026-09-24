# syntax=docker/dockerfile:1
# Drumscore backend image: the API (default command) and the workers
# (`python -m app.worker`) run from this same image. docs/DEPLOYMENT.md.

FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM denoland/deno:bin-2.9.7 AS deno

FROM python:3.13-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    HF_HOME=/opt/huggingface
WORKDIR /app

# Main environment (Python 3.13, the image's own interpreter).
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3.13

# DrumScript's isolated environment (needs Python 3.12; uv installs it under
# /opt/python, which the runtime stage copies to the same path).
COPY drumscript_runner/pyproject.toml drumscript_runner/uv.lock drumscript_runner/.python-version drumscript_runner/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd drumscript_runner && uv sync --frozen --no-install-project

# Bake the Demucs model weights (Demucs 4.1 fetches them from Hugging Face)
# into the image instead of downloading them on a worker's first job.
RUN .venv/bin/python -c "from demucs.pretrained import get_model; get_model('htdemucs')"

FROM python:3.13-slim-trixie
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# yt-dlp's JavaScript runtime for YouTube.
COPY --from=deno /deno /usr/local/bin/deno
RUN useradd --system --uid 10001 --create-home drumscore \
    && mkdir /data \
    && chown drumscore /data

COPY --from=build /opt/python /opt/python
COPY --from=build /opt/huggingface /opt/huggingface
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/drumscript_runner/.venv /app/drumscript_runner/.venv
WORKDIR /app
COPY . .

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface \
    HF_HUB_OFFLINE=1 \
    NUMBA_CACHE_DIR=/tmp/numba \
    MPLCONFIGDIR=/tmp/matplotlib \
    STORAGE_ROOT=/data \
    LOG_FORMAT=json
USER drumscore
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
