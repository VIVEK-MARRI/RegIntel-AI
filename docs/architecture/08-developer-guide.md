# 08 — Developer Guide

## Local setup

### Prerequisites

* Python 3.11+
* Node 20+ (for the frontend)
* PostgreSQL 16+ with the `pgvector` extension
* (Optional) Redis 7+ for rate limiting and ephemeral state
* (Optional) Docker + docker compose for the full stack

### Clone and bootstrap

```bash
git clone https://github.com/regintel/regintel-ai.git
cd regintel-ai
python -m venv .venv
source .venv/bin/activate     # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env          # then edit secrets
pre-commit install            # if available
```

### Run the backend

```bash
# Database
alembic upgrade head

# API
uvicorn app.main:app --reload --port 8000
```

### Run the frontend

```bash
cd frontend
npm install
npm run dev
```

### Run the security self-test

```bash
curl http://localhost:8000/api/v1/security/selftest
```

## Testing

### Layout

```
tests/
  test_security.py        # M10.6 unit tests
  test_security_api.py    # M10.6 HTTP tests
  test_benchmark.py       # M10.5 unit tests
  test_benchmark_api.py   # M10.5 HTTP tests
  test_deployment.py      # M10.3 deployment validation
  test_pipeline.py        # M10.4 CI pipeline validation
  test_milestone{1..9}.py # Prior milestones
  test_<feature>.py       # Per-feature tests
```

### Conventions

* Every new module has a matching test file.
* Tests use `pytest` with `pytest-asyncio` for async.
* HTTP tests use `fastapi.testclient.TestClient`.
* Singleton modules expose `set_<thing>(...)` and `reset_<thing>()`
  helpers; use them to install a fresh instance per test.
* Avoid `time.sleep`; use the framework's clock injection.

### Running tests

```bash
# All tests
pytest

# A specific module
pytest tests/test_security.py

# A specific test
pytest tests/test_security.py::TestJWT::test_refresh_round_trip

# With coverage
pytest --cov=app --cov-report=term-missing
```

## Code style

* **Formatter** — `ruff format` (PEP 8 + project conventions).
* **Linter** — `ruff check`.
* **Type checker** — `mypy app` (relaxed mode).
* **Docstrings** — Google style.
* **Imports** — sorted with `isort` (handled by `ruff`).

### Linting

```bash
ruff check app tests
ruff format --check app tests
mypy app
```

## Architecture rules

* **Composition root** — `app/main.py` is the only place that wires
  singletons. Tests use `set_*` / `reset_*` helpers to swap them out.
* **Public surface** — each package re-exports its public API in
  `__init__.py`. Internal modules use a leading underscore.
* **No cross-package imports of private symbols.** If you need a helper
  from `app.X._internal`, promote it to `app.X.internal` first.
* **Async at the edges, sync in the core.** HTTP handlers are async;
  internal services are sync unless they wrap an external async API.

## Adding a new feature

1. **Plan** — open an issue with the API surface and the data model.
2. **Schema** — add or update Pydantic models in `app/models/`.
3. **Migration** — generate an Alembic migration for any schema change.
4. **Service** — add a service module under `app/<feature>/`. The
   service owns the business logic and is the only place that touches
   the database.
5. **Router** — add `app/api/v1/<feature>.py` with the FastAPI
   router, and register it in `app/main.py`.
6. **Tests** — unit + HTTP tests.
7. **Docs** — update the relevant `docs/architecture/*.md`.

## Adding a new role

1. Add the role to `Role` in `app/security/rbac.py`.
2. Map the role to its `Permission`s in `role_permissions`.
3. Add the role's permission set to the unit test in
   `tests/test_security.py::TestRBAC::test_default_role_grants`.
4. Update `docs/architecture/07-api-reference.md` if the role affects
   the API surface.

## Adding a new secret

1. Decide which sources the secret can come from: `env`, `file`, `vault`.
2. Update `app/security/secrets.py::_lookup_*` if a new source is
   needed.
3. Document the new secret in `docs/architecture/04-deployment-architecture.md`
   (Secrets section).
4. Add the secret name to the integration test in
   `tests/test_security.py::TestSecrets::test_list_known_*`.

## Common pitfalls

* **Singleton leakage** — always reset singletons in test teardown
  (use the `reset_*` helpers).
* **httpx + starlette version mismatch** — the test stack requires
  `httpx==0.27.2` with `starlette==0.27.0`. Newer httpx drops the
  `app=` kwarg that starlette's TestClient uses internally.
* **JWT secret length** — `JWTConfig` rejects secrets shorter than
  32 characters. Tests use 48-character filler strings.
* **Mermaid** — keep diagrams under 200 lines; if a diagram grows
  larger, split it.

## Release process

See `docs/RELEASE_CHECKLIST.md` for the full release procedure. The
short version:

1. Branch from `main` → `release/vX.Y.Z`.
2. Update `RELEASE_NOTES.md`, `docs/VERSIONING.md`, and the version
   constants in `app/__init__.py` and `app/main.py`.
3. Open a PR; CI runs the full suite + benchmark.
4. Merge → tag → release workflow builds + pushes multi-arch images.
5. Smoke test on staging → promote to production.

## Getting help

* Slack: `#regintel-dev`
* Issues: github.com/regintel/regintel-ai/issues
* Email: `dev@regintel.ai`


## See also

* [Architecture index](./README.md)
* [01 â€” System Architecture](./01-system-architecture.md)
* [05 â€” Data Flow](./05-data-flow.md)
* [06 â€” Components](./06-components.md)
* [07 â€” API Reference](./07-api-reference.md)

