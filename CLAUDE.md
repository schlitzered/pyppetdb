# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

pyppetdb is a Python (FastAPI + MongoDB) replacement/middleware for Puppet infrastructure: PuppetDB endpoints, a database-backed Puppet CA, a Puppetserver front-end with catalog caching, a validated Hiera backend (PyHiera), fact-based RBAC, secrets redaction, and a secure job execution engine driven over WebSockets. Docs in `docs/` (mkdocs) — `docs/architecture.md` is the best overview.

## Commands

Use the project venv: `venv/bin/python` (or activate it).

```bash
# Unit tests (no external services needed)
APP_SECRETKEY=ci-test-secret python -m unittest discover tests/unit

# Single test module / case
APP_SECRETKEY=ci-test-secret python -m unittest tests.unit.test_crud_nodes
APP_SECRETKEY=ci-test-secret python -m unittest tests.unit.test_crud_nodes.SomeTestCase.test_something

# Integration tests (require a MongoDB replica set; they self-skip if unreachable)
MONGODB_URL="mongodb://localhost:27017/?replicaSet=rs0" APP_SECRETKEY=ci-test-secret \
  python -m unittest discover tests/integration

# Lint (config in pyproject.toml: ignores E501,W503)
flake8 pyppetdb
```

Tests are stdlib **unittest**, not pytest — do not install or use pytest.

The server runs via the `pyppetdb` console script (`pyppetdb.main:main`). Configuration is entirely environment variables / a `.env` file (pydantic-settings), nested with `_` as delimiter (`app_main_port` → `app.main.port`); list values are JSON strings. `app_secretkey` is required or the process won't start. Full reference: `docs/configuration_reference.md`.

## Architecture

One FastAPI app on a single port; three router groups toggled by config flags and distinguished by URL prefix:

- `/api`, `/oauth` — management REST API (`app_main_enable`)
- `/puppet`, `/puppet-ca` — Puppetserver front-end + Puppet CA (`app_puppet_enable`)
- `/pdb` — PuppetDB command/query endpoints (`app_puppetdb_enable`)

MongoDB **must be a replica set**: change streams drive cache invalidation, inter-instance coordination, and live job logs. Multiple identical replicas share one MongoDB and coordinate over an inter-instance WebSocket mesh.

### Layering

Request flow is controller → crud → MongoDB, with Pydantic models at the boundaries:

- `pyppetdb/controller/` — FastAPI routers, directory structure mirrors URL structure (`controller/api/v1/`, `controller/puppet/v3/`, `controller/puppet_ca/v1/`, `controller/pdb/cmd|query/`, `controller/oauth/`).
- `pyppetdb/crud/` — one class per MongoDB collection (plus `mixins.py` for filtering/sorting/pagination/projection and `common.py` for the base `Crud`). All crud instances are registered with `CrudManager` so `init_all()` creates indexes/watchers.
- `pyppetdb/model/` — Pydantic request/response schemas, file names parallel the crud files.
- `pyppetdb/container.py` — `AppContainer` is the composition root that wires everything (cruds, services, redactors, authorizers). **Adding a collection touches all four places**: model file, crud file, registration in `AppContainer`, controller. It also bootstraps the default `puppet-ca` CA authority/space on startup.
- `pyppetdb/main.py` — settings, logging (structlog), TLS/uvicorn setup with custom protocols that capture client certs (`ca/protocol.py`), app assembly, background workers.

### Subsystems

- `pyppetdb/ca/` — `CAService` implements the CA (signing, revocation, CRLs, secret resolution). CA data lives in MongoDB, so every instance can act as CA. Revocations propagate to the `AuthorizeClientCert` validators via listeners registered in `container.py`.
- `pyppetdb/authorize/` — `AuthorizePyppetDB` (fact-based RBAC: Teams → node-group fact matching) and `AuthorizeClientCert` (mTLS client cert validation against the CA collections, used for `/puppet` and `/pdb`).
- `pyppetdb/ws/` — `WsHub` owns agent WebSocket connections and log-subscription fan-out; `inter_api.py` is the instance-to-instance relay used when a job request lands on a different instance than the one holding the agent connection; `remote_executor.py` speaks the agent job protocol. `pyppetdb/jobs/service.py` handles job scheduling/expiry/dispatch.
- `pyppetdb/hiera/` — PyHiera integration. Key models come from static plugins (Python modules loaded via `importlib` from `app_main_hiera_keyModels`) or dynamic JSON-schema-like definitions stored in MongoDB (`hiera/schema_model_factory.py`). `pyppetdb_dummy_plugin/` is the example plugin package used by tests.
- Secrets redaction: `NodesDataProtector` / `NodesSecretsRedactor` and the catalog/report redactors (in `crud/nodes_*`) redact at **read time** on `/api` routes only — `/puppet` routes serve unredacted data to agents, and MongoDB stores the full data.

### Testing conventions

- `tests/unit/` uses mocks throughout; file names map to source (`test_crud_nodes.py` → `pyppetdb/crud/nodes.py`, `test_api_v1_*` → `controller/api/v1/*`).
- `tests/integration/` boots the real app via `IntegrationTestBase` (`tests/integration/base.py`) with a real MongoDB (`pyppetdb_test` database) and FastAPI `TestClient`; skips itself when MongoDB is unreachable.

## Code style

- No `#` comments and no docstrings — write self-explanatory code. Keep the Apache 2.0 license header at the top of every source file (copy it from any existing file when creating new ones).
- flake8 with `E501,W503` ignored is the only linter; there is no formatter config, but the codebase follows Black-style formatting.
