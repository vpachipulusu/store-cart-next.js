FROM python:3.12-slim-bookworm

# uv comes from a pinned, digest-locked image instead of `curl | sh` (ADR-006).
# Bump the version and digest together.
COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /uvx /bin/

# Unprivileged runtime user; /app is the only path it owns.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir /app \
    && chown app:app /app

WORKDIR /app
USER app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Copy dependency files first to leverage Docker caching
COPY --chown=app:app pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen

# Copy the rest of the application code (see .dockerignore)
COPY --chown=app:app . .

EXPOSE 8000

CMD ["./start.sh"]
