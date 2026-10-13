# CLAUDE.md (fastapi_backend)

Guidance for agents working on the StoreCart FastAPI service. Repo-wide rules (Jira flow, branches, baton) are in
[`../AGENTS.md`](../AGENTS.md) and [`../.claude/CLAUDE.md`](../.claude/CLAUDE.md). Run every command below from
`fastapi_backend/`. Decisions: [ADR-003](../docs/adr/0003-nextjs-to-fastapi-authentication.md),
[ADR-004](../docs/adr/0004-backend-layering.md), [ADR-007](../docs/adr/0007-rate-limit-keys.md),
[ADR-008](../docs/adr/0008-api-client-generation.md).

## Commands

```bash
uv sync                                          # install (Python 3.12, uv only; no pip)
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000 --reload
uv run ruff check .                              # lint (add --fix to apply)
uv run ruff format .                             # format (CI runs --check)
uv run mypy                                      # strict; checks app/ and commands/
uv run pytest                                    # all tests, no network, no database
uv run pytest --cov --cov-report=term-missing:skip-covered   # CI form
uv run alembic upgrade head                      # only against a database you own (see Alembic)
```

- **Coverage floor.** `[tool.coverage.report] fail_under` in `pyproject.toml` fails `pytest --cov` below the
  floor. It is a ratchet: raise it when coverage rises, never lower it, and do not invent a fixed target. The
  owner decides the number.
- **OpenAPI and the client.** After any change to routes, schemas or `ERROR_RESPONSES`, regenerate the schema and
  check the TypeScript client:

  ```bash
  uv run python -m commands.generate_openapi_schema   # writes ../nextjs-frontend/openapi.json (LF)
  cd ../nextjs-frontend && npm run generate:client    # then: npm run check:client
  ```

  Commit `openapi.json` and `src/lib/api/generated/`. `uv run python -m commands.check_openapi_schema` fails when
  the committed schema is stale.
- **Dependencies.** Edit `pyproject.toml` (pin exact versions for risky or fast-moving packages), then
  `uv lock` and `uv export --frozen --no-dev --no-hashes --quiet -o requirements.txt`. The pre-commit hook fails
  when `requirements.txt` is out of sync.
- **Alembic.** `alembic_migrations/` holds an empty baseline (ADR-011). No build runs `upgrade head`; create a
  revision with `uv run alembic revision --autogenerate -m "<msg>"` and run it only against a database you own.
- **Pre-commit.** `uvx pre-commit run --from-ref origin/main --to-ref HEAD` before opening a PR.
- Keep LF line endings in committed files.

## Layering (routers > services > repositories)

```
app/api/v1/        routers: HTTP only. Parse and validate input, call one service, shape the response.
app/api/           dependencies (deps.py), rate-limit dependencies (rate_limit.py), route ids.
app/services/      business logic and transaction boundaries. No FastAPI imports.
app/repositories/  SQLAlchemy queries for one aggregate each. No business rules. Receive an AsyncSession.
app/core/          config, logging, errors, request id, rate-limit primitives, database seam, Sentry.
```

Import direction is one way: routers may import services, schemas and `core`; services may import repositories
and `core`; repositories may import `core` and SQLAlchemy models only. Never import upward (a service must not
import `fastapi`, a repository must not import a service). Repositories never create sessions, engines or
session makers: those live behind `app.core.database` (`SessionProvider`), and routers get them through
`app/api/deps.py`, the single place where concrete implementations are wired.

## Conventions

- **Error envelope.** Every error body is `{"success": false, "error": "<message>"}` (`app.core.errors`).
  Raise `HTTPException` (or a domain error mapped to one) with a plain message; validation errors become a 422
  with `"Invalid request"`; anything unhandled becomes a 500 with `"Internal server error"` and no internals.
  New routes need no extra `responses=` for 422 and 500: they are declared on the app.
- **Request ID.** `RequestIdMiddleware` generates an ID per request (never trusted from the client), returns it
  as `X-Request-ID`, stores it in `request_id_var`, and tags Sentry with it. Log with the standard `logging`
  module (JSON, no `print`); the ID is added to every record automatically.
- **Sentry (KAN-35).** `app.core.sentry.init_sentry` runs in `create_app()` and does nothing unless `SENTRY_DSN`
  is set (leave it unset locally and in tests). Environment comes from `VERCEL_ENV`, else `ENVIRONMENT`; release
  from `VERCEL_GIT_COMMIT_SHA`. Events are scrubbed in `scrub_event` (Authorization, Cookie, X-Session-Token,
  X-Internal-Key, bodies, cookies; frame locals are off). The 500 handler only logs: the SDK reports the
  exception once. To report something you handle yourself, call `app.core.sentry.report_exception(exc)`.
- **Rate limiting (ADR-007).** Per-route dependencies in `app/api/rate_limit.py`: `limit_by_subject` for
  authenticated routes, `limit_auth_attempts` for sign-in, sign-up and password reset. Policies live in
  `app/core/rate_limit.py`; the limiter is injected via `get_rate_limiter`. Auth policies fail closed (503),
  api and webhook policies fail open with a warning and a Sentry event.
- **Config and fail-fast.** All settings come from `app.core.config.Settings` (pydantic-settings); never read
  `os.environ` elsewhere. Required values (`DATABASE_URL`) and production-only requirements (Upstash) are
  validated at import time so a misconfigured deployment refuses to start. `ENVIRONMENT` defaults to
  `production`; only `local` and `test` (or Vercel `preview`/`development`) relax checks. Secrets are
  `SecretStr` and are never logged. Add new variables to `.env.example` and
  `docs/developer/getting-started.md`.
- **Style.** Strict typing (mypy strict), small functions, immutable data (`@dataclass(frozen=True)`), no
  hardcoded secrets, docstrings only where the why is not obvious.

## Test conventions

- Tests live in `tests/` mirroring `app/` (`api`, `core`, `services`, `repositories`, `commands`). No test may
  use the network or a real database, Redis or Sentry: `tests/conftest.py` sets placeholder settings.
- **Fakes via Protocol, not mocks of internals.** Depend on a small `Protocol` (`SessionProvider`,
  `RateLimiter`) and inject a fake from `tests/fakes.py` (`FakeSessionProvider`, `FakeRateLimiter`,
  `RaisingRateLimiter`). In API tests replace the dependency with `app.dependency_overrides`, or build a small
  FastAPI app with only the pieces under test, and clear overrides afterwards.
- **AAA.** Arrange, Act, Assert, in that order, one behaviour per test, named for the behaviour
  (`test_returns_503_when_database_is_unreachable`).
- API tests use `httpx.AsyncClient` with `ASGITransport` (`raise_app_exceptions=False` to see the 500
  envelope); `asyncio_mode = auto`, so async tests need no marker.
- For Sentry, use a recording `Transport` (see `tests/core/test_sentry.py`); never send real events.
- Fix the implementation, not the test, unless the test is wrong. New code ships with tests; keep coverage at or
  above the floor.
