# syntax=docker/dockerfile:1.7

# ---- Base -------------------------------------------------------------------
# A single slim Python base reused by the build and runtime stages.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- Builder ----------------------------------------------------------------
# Installs runtime dependencies into an isolated prefix that is copied into the
# final image. Keeping build tooling out of the runtime image reduces size and
# attack surface.
FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# BuildKit cache mount: pip's download/wheel cache persists across builds
# (keyed by this stage's cache id) without ending up in any image layer --
# faster rebuilds when only the app's own source changed, with no size cost.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

# ---- Runtime ----------------------------------------------------------------
FROM base AS runtime

# Create an unprivileged user to run the application.
RUN groupadd --system app && useradd --system --gid app --create-home app

# Copy installed dependencies from the builder.
COPY --from=builder /install /usr/local

# Copy application source.
COPY --chown=app:app . /app

USER app

EXPOSE 8000

# Liveness for orchestrators that support HEALTHCHECK.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live').status==200 else sys.exit(1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
