# Atlas API container (see docs/DEPLOYMENT_PLAN.md).
# Build from the paper-radar directory: docker build -f api/Dockerfile .
# Supply-chain: consider pinning the base by digest (FROM python:3.12-slim@sha256:…)
# and bumping it via Dependabot so a moved tag can't change what ships.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv==0.5.24

WORKDIR /app

# Install deps first so source edits don't bust the layer cache. UV_NO_CACHE
# keeps ~200MB of wheel cache out of the image layers (layer caching already
# skips unchanged installs, so the uv cache buys nothing here).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra api --no-dev --no-install-project

# README.md is needed to build the project wheel (readme in pyproject.toml).
COPY README.md ./
COPY paper_radar ./paper_radar
COPY api ./api
RUN uv sync --frozen --extra api --no-dev

# Drop root: an RCE (or a compromised dependency) in the app then runs as an
# unprivileged user, unable to read the injected fly secrets as root or alter
# the image at runtime. The app is stateless and the uv venv is world-readable,
# so no chown is needed (a recursive chown would copy the whole venv into its own
# layer, doubling the image size).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

# 8080 is a default, not a constant: hosts that inject $PORT (Railway/Render)
# work unchanged; fly.toml's internal_port matches the default.
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
