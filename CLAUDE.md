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
- `pyppetdb/pdbquery/` — the PuppetDB query engine behind `/pdb/query/v4`. `entities.py` maps each PuppetDB entity onto the MongoDB documents via a `$project` whose keys are the PuppetDB column names, `ast.py` parses/compiles the AST query language, `engine.py` builds and runs the aggregation pipeline, `matcher.py` is the Python-side evaluator for entities expanded in Python (`fact-paths`, `fact-contents`). That expansion (`QueryEngine._run_python`) streams the cursor in `PYTHON_BATCH_SIZE` batches through `asyncio.to_thread`, checks the query deadline per document (an `asyncio.timeout` cannot interrupt synchronous code — an unfiltered `fact-contents` query over 10k nodes used to freeze the whole instance for half an hour), stops reading once `offset + limit` rows are in hand unless `include_total`, `order_by`, aggregation or `distinct_rows` need everything, and projects only `facts.<name>` when the filter pins `name`. Because the compiled `$match` uses column names it must sit behind the `$project`; `engine.py` therefore derives a **document pre-filter** (storage paths, runs first, uses the indexes) and an **element filter** (pushed into the projection's `$filter` so arrays are narrowed before `$unwind`) from it. Both are derived only from positive-polarity clauses so they can only over-match — never drop a row the full `$match` would keep. `app_puppetdb_querySource` switches queries between this engine and an upstream OpenVoxDB; commands are always stored locally and forwarded upstream when `app_puppetdb_serverurl` is set. Conformance corpus and coverage tool in `tests/conformance/`.
- `pyppetdb/hiera/` — PyHiera integration. Key models come from static plugins (Python modules loaded via `importlib` from `app_main_hiera_keyModels`) or dynamic JSON-schema-like definitions stored in MongoDB (`hiera/schema_model_factory.py`). `pyppetdb_dummy_plugin/` is the example plugin package used by tests.
- `pyppetdb/ingest.py` — `IngestQueue`, a bounded background work queue created in `AppContainer` and used by `/pdb/cmd/v1`. One command becomes one queued job; everything touching MongoDB runs on its workers, never on the request path. Jobs enforce the Puppet-run order per node — `replace_catalog` is discarded when the node has no facts, `store_report` when it has no catalog (`CrudNodes.get_ingest_state`). When full the endpoint blocks up to `app_puppetdb_writeQueueWaitTimeout` for a free slot (`IngestQueue.enqueue`, woken by the workers after every dequeue) and only then answers 503 with `Retry-After` — a rejected `store_report` is lost, because Puppet Server does not spool commands. CPU-bound work on the command path (gzip/JSON decode, catalog and report normalisation, building the resource documents, the history model) runs in `asyncio.to_thread` so it does not stall the event loop that all queue workers share. Sized via `app_puppetdb_writeQueueSize` (memory) and `app_puppetdb_writeQueueWorkers` (MongoDB concurrency); depth and counters are reported under `/status/v1/services`.
- `replace_catalog` skips rewriting the embedded catalog when the incoming **content hash** (resources + edges, excluding the per-compile `version`/`catalog_uuid`/`transaction_uuid`/`producer_timestamp`) matches what is stored; only `resources`/`edges` are skipped — the per-compile metadata (`catalog_uuid`, `transaction_uuid`, `version`, `hash`, `producer_timestamp`, ...) is still `$set` via `update_catalog_metadata`, and `change_catalog` is still updated so `catalog_timestamp` keeps PuppetDB's "last received" semantics. The check runs inside the background task, never on the request path.
- Query-path performance rules that are easy to break: when a filter pins the fact `name` to constants, `build_pinned_keys` replaces `$objectToArray` with a literal `[{k, v: "$facts.<name>"}]` array so nothing is unwound; the exact `$match` still runs behind it, so an over-broad key set stays correct.
- Query-path performance rules that are easy to break: the compiled `$match` is written in column names and therefore runs *after* the `$project`, so anything that rewrites values (date formatting) must come after it, never inside it. `build_projection` emits only `projected=True` columns plus whatever the filter/`order_by` needs, and the helpers are removed again with `$unset`; `Entity` has no `projection()` method any more. `fact-names`, `environments` and `producers` carry a `distinct_field` and are served by `collection.distinct` (a `DISTINCT_SCAN`, no documents examined) whenever the query is unfiltered, unprojected and unaggregated; there is no aggregate cache any more.
- `node_state` on `reports`/`events` is **materialised**: `nodes_reports` documents carry a top-level `disabled` mirroring `nodes.disabled`, so the column pre-filters like any other instead of expanding into a cross-collection subquery. Every write path that touches `nodes.disabled` propagates it with a conditional `update_many` (`CrudNodesReports.set_node_disabled`, filtered on `disabled: {$ne: <new>}`), so the steady-state Puppet run costs one index seek and no writes. Both `/pdb` command jobs (`_propagate_node_state`, reached from `_job_update_node` *and* `_job_replace_facts`, which bypasses it) and the `/api` node update must call it. Documents predating the field read as `active`, which is the correct default, so no migration is needed.
- Query guards, all configurable and all upstream-derived: `app_puppetdb_maxQueryDepth` (AST nesting, corpus maximum is 12), `app_puppetdb_maxSubqueryDepth` (round trips, corpus maximum is 2) and `app_puppetdb_queryTimeout`/`queryTimeoutMax` with the `?timeout=` parameter. `check_depth` recurses with a **countdown budget**, so it never descends deeper than the limit it enforces — computing the full depth first and comparing afterwards would blow the stack on exactly the queries it exists to reject. With `maxQueryDepth` disabled that budget is gone, so the call is wrapped in a `RecursionError` guard that still answers 400. Subquery results are de-duplicated inside the aggregation (`$group` before `$limit`), so `SUBQUERY_LIMIT` counts distinct values rather than raw rows. `app_puppetdb_maxPageSize` caps only client-facing result sets: `QueryEngine.run(..., page_cap=False)` is how `event-counts`/`aggregate-event-counts` fetch the events they summarise in Python — capping that query silently truncates the counts (10k events over 10k nodes became 834 rows). `~>` follows upstream's two implementations: on `fact-paths` every regex must match its path element **in full** (`re.fullmatch`, upstream joins the array into one `^el#~el$` regex over the encoded path), on `fact-contents` each element is an unanchored `re.search` (upstream's `path-array` match) — the compiler picks `__regex_array_full__` or `__regex_array__` per entity; `~` stays an unanchored search everywhere.
- Fact queries ride on `facts_index`, a flat `[{p, v?}]` array written next to `facts` on every fact write (`build_facts_index` in `helpers/puppetdb.py`, applied in `CrudNodes._with_facts_index` so no write path can skip it) and covered by the single compound multikey index `idx_facts_index` on `(facts_index.p, facts_index.v)`. Every top-level fact name is always present (that is what `fact-names` reads) and costs exactly one entry: `{p, v}` when the value is an indexable scalar, a bare `{p}` when it is structured, denied or oversized; deeper paths and list elements add further `{p, v}` entries at an indexable path (`app_main_facts_indexDepth`, `app_main_facts_indexMaxValueLen`, `app_main_facts_indexDeny`), lists not consuming a depth level so array facts match MongoDB's implicit array traversal. An indexable fact equality compiles to **both** forms — the `$elemMatch` on `facts_index` (what the generic index serves) *and* the direct `facts.<path>` predicate (O(1) residual, plus any dedicated `app_main_facts_index` index); emitting only one of them is measurably slower. Soundness rule: because a pre-filter may only over-match, the engine emits the `$elemMatch` only when its own indexability check — identical to the ingest rule, fed from the config through the `QueryEngine` constructor, never read globally — guarantees the entry was written; everything else falls back to the direct predicate. There is no backfill, so changing the config only takes effect on the next Puppet run of a node.
- Secrets redaction: `NodesDataProtector` / `NodesSecretsRedactor` and the catalog/report redactors (in `crud/nodes_*`) redact at **read time** on `/api` routes only — `/puppet` routes serve unredacted data to agents, and MongoDB stores the full data.

### Testing conventions

- `tests/unit/` uses mocks throughout; file names map to source (`test_crud_nodes.py` → `pyppetdb/crud/nodes.py`, `test_api_v1_*` → `controller/api/v1/*`).
- `tests/integration/` boots the real app via `IntegrationTestBase` (`tests/integration/base.py`) with a real MongoDB (`pyppetdb_test` database) and FastAPI `TestClient`; skips itself when MongoDB is unreachable.

## Code style

- No `#` comments and no docstrings — write self-explanatory code. Keep the Apache 2.0 license header at the top of every source file (copy it from any existing file when creating new ones).
- flake8 with `E501,W503` ignored is the only linter; there is no formatter config, but the codebase follows Black-style formatting.
