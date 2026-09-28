# PuppetDB compatibility

pyppetdb serves the PuppetDB command and query API under `/pdb`, backed by its own
MongoDB store. Agents and PuppetDB clients (Puppetboard, `puppet query`, exported
resource collection, PE-style consoles) can talk to it directly.

## Where answers come from

Two independent decisions:

- **Writes** — every `/pdb/cmd/v1` command is stored in pyppetdb's database. If
  `app_puppetdb_serverurl` is set, the same command is *additionally* forwarded to that
  upstream OpenVoxDB/PuppetDB. This is unconditional; there is no switch to turn it off
  other than removing `serverurl`.
- **Queries** — `app_puppetdb_querySource` decides who answers. `internal` (the default)
  uses pyppetdb's own query engine; `upstream` proxies every query to
  `app_puppetdb_serverurl` and passes the response through unchanged, including the
  `X-Records` header.

```
app_puppetdb_serverurl = https://openvoxdb.example.com:8081
app_puppetdb_querySource = upstream
```

Setting `querySource = upstream` without a `serverurl` is a configuration error and the
process refuses to start.

## Commands

`POST /pdb/cmd/v1?certname=&command=&version=&producer-timestamp=`

| Command | Stored as |
|---------|-----------|
| `replace_facts` | node facts, `producer`, `producer_timestamp`, `package_inventory` |
| `replace_catalog` | catalog resources (with per-resource hash, `file`, `line`), edges, `version`, `transaction_uuid`, `code_id`, catalog hash |
| `replace_catalog_inputs` | `catalog_inputs` on the node |
| `store_report` | report history entry, marked as the node's latest report |
| `deactivate_node` | sets the node inactive |

The response is `200` with `{"uuid": "..."}`, matching PuppetDB.

Commands for one node must arrive in the order of a Puppet run: `replace_facts` first,
then `replace_catalog`, then `store_report`. A catalog for a node that has no facts yet
and a report for a node that has no catalog yet are **discarded** by the worker (logged
as a warning; the client still received its `200`). There is no buffering or reordering —
the agent's next run repairs the state. Because commands are processed asynchronously,
a report submitted while its catalog is still queued can hit this rule; with a normal
queue depth the seconds between the agent's catalog request and its report are ample.

`replace_catalog` computes a content hash over the resources and edges only. When it
matches what is stored, the resources and edges are not rewritten; only the metadata
(`change_catalog`, `environment`, `producer`, `catalog_uuid`, `transaction_uuid`, ...) is
updated, so `catalog_timestamp` still reflects when the catalog was last *received*,
matching PuppetDB. Catalog history is written once per `catalog_uuid`, so a recompile
with identical content still gets its history entry while a retried command does not.

The comparison happens in the background task, not on the request path, so it does not
add latency to the agent's command submission.

## Write queue

A command is parsed and normalised on the request path — CPU work only, roughly 1.5 ms
for a 200-resource catalog — and everything that touches MongoDB is handed to a bounded
queue drained by `app_puppetdb_writeQueueWorkers` workers. One command becomes one queued
job, so the queue depth is the number of pending commands.

When the queue is full the endpoint answers `503` with `Retry-After` rather than letting
the backlog grow. The agent logs the failure and submits again on its next run; nothing
is buffered on disk. This is deliberate: the alternative is unbounded memory growth under
sustained overload, with the client never feeling any pressure.

### What a `200` means

A `200` with `{"uuid": ...}` means *accepted into the in-memory queue*, not *persisted*.
The write happens later, on a worker, and the client is already gone by then:

- If the worker fails — MongoDB unreachable, or a payload that only fails validation once
  the full model is built — the command is **lost**. The failure is logged and counted in
  `failed` under `/status/v1/services`; there is no retry and the client is never told.
- On a graceful shutdown the queue is drained first, bounded by `app_puppetdb_writeQueueDrainTimeout` (default 30 s); whatever
  is still queued when that expires is discarded (and logged). On a crash or `SIGKILL`
  the whole in-memory queue is gone.

This is a deliberate trade: a persistent queue would make every command survive a
restart at the cost of a second durable store on the write path. Puppet agents resend
their facts, catalog and report on every run, so a lost command is repaired by the next
run — but monitoring `failed` and `dropped` is the only way to notice that it happened.

A filter that pins the fact `name` to one or a few constants (`["=", "name", "osfamily"]`
or an `in` over an array) bypasses the fact-map expansion entirely: the key is known, so
the value is read straight from `facts.<name>` instead of turning the whole map into an
array and unwinding it.

## Fact index

Facts are stored embedded on the node document, so only the facts listed in
`app_main_facts_index` get a dedicated index; everything else would be a collection scan.
Every fact write therefore also stores a flat companion array `facts_index`, one entry per
indexable fact path, covered by a single compound multikey index
`(facts_index.p, facts_index.v)`. One index serves every fact instead of one index per
configured fact, and the planner picks the most selective fact of a multi-fact query
itself.

Every top-level fact name is present in the index — that is what `/fact-names` reads —
and costs exactly one entry when its value is an indexable scalar: `{p: <name>, v: <value>}`.
A fact whose value is structured, denied or too long to index keeps a bare `{p: <name>}`
entry instead, so the name stays visible without the value ever churning. A value is
indexable when its path is no deeper than `app_main_facts_indexDepth`, is not matched by
`app_main_facts_indexDeny`, and the value is a bool, a number, or a string no longer than
`app_main_facts_indexMaxValueLen` characters. Any key is a valid path segment — including
`mountpoints` keys such as `/boot` — except an empty one, one containing a NUL byte or
starting with `$` (not addressable as a MongoDB field), and a purely numeric one: under a
dotted path MongoDB reads `roles.0` as an array index as well as a key, so indexing it
would let the pre-filter drop rows. Lists do not consume a depth level; their
scalar elements are indexed under the path of the list itself, mirroring MongoDB's implicit
array traversal, so `{"facts.roles": "web"}` and the index agree on a list-valued fact.

A fact equality compiles to **both** an `$elemMatch` on `facts_index` and the direct
`facts.<path>` predicate. The `$elemMatch` is what the generic index can serve; the direct
predicate is an O(1) residual check that also uses a dedicated `app_main_facts_index`
index when one exists. Emitting only the `$elemMatch` form is measurably slower on
multi-fact queries, so both are always emitted.

The document pre-filter may only over-match — it runs before the exact `$match` and
anything it drops is gone. An `$elemMatch` is therefore only emitted when the engine's
indexability check says ingest is guaranteed to have written that entry, using exactly the
same rule (type, length, depth, deny list) as the ingest side. Everything else — regular
expressions, ranges, `null?`, oversized or denied values, paths deeper than the configured
depth — falls back to the direct predicate alone.

There is no backfill: changing `indexDepth`, `indexMaxValueLen` or `indexDeny` only takes
effect for nodes that send facts again afterwards.

`fact-names` is served by a `distinct` on `facts_index.p` (a covered `DISTINCT_SCAN` that
examines no documents), `environments` and `producers` by a `distinct` on their own indexed
fields. A filtered, projected or aggregated query on those entities still runs the full
pipeline.

## Sizing

Size the deployment for the case where *every* catalog has changed — a module rollout
touching all nodes — and treat the unchanged-catalog skip as a saving rather than as
capacity.


## Query endpoints

All endpoints accept `GET` (with a `query` URL parameter) and `POST` (with a
`{"query": ...}` body or a bare AST array).

| Endpoint | Notes |
|----------|-------|
| `/pdb/query/v4` | root endpoint, requires a `["from", <entity>, ...]` query |
| `/pdb/query/v4/nodes`, `/nodes/{certname}` | plus `/facts`, `/resources`, `/reports`, `/events` subpaths |
| `/pdb/query/v4/facts`, `/facts/{name}`, `/facts/{name}/{value}` | |
| `/pdb/query/v4/fact-names`, `/fact-paths`, `/fact-contents`, `/factsets` | |
| `/pdb/query/v4/inventory` | dotted access to `facts.` and `trusted.` |
| `/pdb/query/v4/resources`, `/resources/{type}`, `/resources/{type}/{title}` | all resources, not just exported ones |
| `/pdb/query/v4/edges`, `/catalogs`, `/catalogs/{certname}` | |
| `/pdb/query/v4/catalog-inputs`, `/catalog-input-contents` | |
| `/pdb/query/v4/packages`, `/package-inventory` | from `package_inventory` in `replace_facts` |
| `/pdb/query/v4/reports`, `/events` | |
| `/pdb/query/v4/event-counts`, `/aggregate-event-counts` | `summarize_by`, `count_by`, `counts_filter` |
| `/pdb/query/v4/environments`, `/environments/{name}/...`, `/producers` | |
| `/pdb/meta/v1/version`, `/pdb/meta/v1/server-time` | |
| `/status/v1/services` | unauthenticated service status |

## Query language

The AST dialect is supported:

- boolean `and`, `or`, `not`
- comparison `=`, `~`, `>`, `<`, `>=`, `<=`, `null?`, `~>` (regexp match on fact paths)
- `in` against an `array` literal or a subquery (`select_<entity>` or a nested `from`)
- `subquery` for implicit relationships between entities
- `extract` with column lists, `group_by`, and the `count`, `avg`, `sum`, `min`, `max`
  and `to_string` functions
- field forms `["fact", "<name>"]`, `["parameter", "<name>"]`, `["node", "active"]`, and
  dotted paths such as `parameters.owner` or `facts.os.family`
- paging via `limit`, `offset` and `order_by` — both as AST clauses and as URL
  parameters — plus `include_total`, which sets the `X-Records` response header

Unknown fields, unknown operators and malformed paging parameters are answered with
HTTP 400 and an explanatory message rather than an empty result.

Subqueries are materialised: the inner query runs first, its distinct values (at most
100,000) become an `$in` on the outer query, and MongoDB serves that from the index.
A single-column subquery such as `["extract", "certname", ["select_resources", ...]]`
is answered by a distinct scan when the inner filter is indexable (`type`, `type` plus
`title`, or `certname` on resources), so it costs one index seek per distinct value
rather than one per matching resource. A multi-column `in` checks the tuples with a
computed key and a set lookup, so its cost grows with the page, not with the number of
tuples. When the inner result exceeds MongoDB's 16 MB command limit the query is
rejected with HTTP 400 (`subquery result too large`).

Events are stored twice: embedded in the report document, which is what the `reports`
entity serves, and once per event in the `nodes_events` collection, which serves
`/events`, `/event-counts` and `/aggregate-event-counts`. The collection is indexed on
`certname`, `report`, `status`, `latest_report?` and `resource`, each combined with
`timestamp`, so the usual dashboard queries (events of the latest reports ordered by
time, failed events, events of one node or report) are index range scans. The counts
endpoints are aggregated in MongoDB; a query that pins `latest_report? = true` or a
report hash is answered from a covering index without touching the documents, anything
else de-duplicates event identities per bucket first. Storing a report therefore costs one extra insert per event plus index
maintenance; a run with 40 changed resources measured about 20 % lower report
throughput than the embedded-only model.

**PQL is not supported.** A `query` parameter that is not a JSON array is rejected with
a 400 explaining that an AST query is required.

## Migration: removed extensions

`/pdb/query/v4/resources` used to be served by a hand-written translator with
pyppetdb-specific extensions. It has been replaced by the shared query engine, which
speaks standard PuppetDB AST only.

**`fact_<name>__<sub>` pseudo-fields are gone.** The old translator accepted a field name
starting with `fact_`, stripped the prefix and turned `__` into `.`, so
`fact_os__release__major` matched the node's `facts.os.release.major`:

```json
["and", ["=", "type", "File"], ["=", "fact_os__release__major", "12"]]
```

That field does not exist in PuppetDB, and the engine now answers `400` with
`'fact_os__release__major' is not a queryable object for resources.` Express it as a
subquery against `facts` instead — `value` accepts dotted paths into structured facts:

```json
["and",
 ["=", "type", "File"],
 ["in", "certname",
  ["extract", "certname",
   ["select_facts",
    ["and", ["=", "name", "os"], ["=", "value.release.major", "12"]]]]]]
```

For a flat fact the inner filter is just `name` and `value`:

```json
["in", "certname",
 ["extract", "certname",
  ["select_facts", ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]]]]]
```

`["extract", ..., ["from", "facts", ...]]` and the `subquery` operator work as well, and
`/inventory` takes dotted fact paths directly (`["=", "facts.os.release.major", "12"]`)
when the resource columns are not needed.

Two more differences at the same endpoint:

- It used to return **only exported** resources. It now returns all of them; add
  `["=", "exported", true]` to get the old result set.
- A query it could not translate used to yield an empty list. Unknown fields and
  operators are now a `400` with a message.

`app_puppetdb_resourceQueryInternal=false` still forces this one endpoint upstream, but
it is deprecated in favour of `app_puppetdb_querySource`.

## Conformance corpus

`tests/conformance/` holds a query corpus extracted from upstream OpenVoxDB — its HTTP
test suite and the load profiles of real consumers — plus a tool that reports which
parts of it the current implementation accepts:

```bash
venv/bin/python tests/conformance/coverage.py
```

`tests/unit/test_pdb_query_corpus.py` runs the same corpus as a regression test.

`tests/conformance/diff_api.py` goes further: it runs the same queries against pyppetdb
and a real OpenVoxDB holding identical data and compares the responses field by field.

## Known divergences from PuppetDB

- **Hashes differ.** `hash`, `latest_report_hash`, `report` and `resource` are computed
  from the same content but with a different algorithm, so they never match upstream.
  Anything embedding them (the `href` of a child collection) differs too.
- **`corrective_change` is populated.** Upstream gates it behind a flag that is off in the
  open-source build and returns `null`; pyppetdb returns the value the agent sent, on
  events and on `latest_report_corrective_change`.
- **`resource_events.data` is always `null`.** The `href` resolves to the full event list.
  Upstream inlines the data for small result sets; computing it on every report query cost
  roughly a factor of seven.
- **Order within child collections is not stable.** `factsets.facts`, `catalogs.resources`
  and resource `tags` hold the same members as upstream but not necessarily in the same
  order.
