# Atlas API container (see docs/DEPLOYMENT_PLAN.md).
# Build from the paper-radar directory: docker build -f api/Dockerfile .
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv==0.5.24

WORKDIR /app

# Install deps first so source edits don't bust the layer cache.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra api --no-dev --no-install-project

# README.md is needed to build the project wheel (readme in pyproject.toml).
COPY README.md ./
COPY paper_radar ./paper_radar
COPY api ./api
RUN uv sync --frozen --extra api --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

# 8080 is a default, not a constant: hosts that inject $PORT (Railway/Render)
# work unchanged; fly.toml's internal_port matches the default.
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
