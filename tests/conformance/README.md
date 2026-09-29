# PuppetDB conformance corpus

Query corpus extracted from upstream OpenVoxDB, plus a tool that reports which
parts of it the current pyppetdb `/pdb` implementation can serve.

## Corpus

`corpus/openvoxdb_queries.json` — 530 entries (498 AST queries, 32 PQL strings)
harvested from `test/puppetlabs/puppetdb/http/*_test.clj`. Entries carry
`expects_error: true` when the surrounding `testing` block asserts HTTP 400.

`corpus/locust_queries.json` — 49 entries from `locust/load-test/*.yaml`: the
queries the PE console, CD4PE and estate-reporting actually send.

`corpus/upstream_features.json` — operators, fields, entities and functions
used per endpoint.

Only the queries are portable. Upstream compares against fixtures written
straight into PostgreSQL, so the expected result sets are not part of this
corpus.

## Regenerating

```bash
git clone --depth 1 https://github.com/OpenVoxProject/openvoxdb /tmp/openvoxdb
venv/bin/python tests/conformance/extract_upstream.py /tmp/openvoxdb
```

## Coverage matrix

```bash
venv/bin/python tests/conformance/coverage.py
```

Needs no MongoDB — it enumerates the routes `ControllerPdb` registers and runs every
corpus query through the real query engine in `pyppetdb/pdb/query/`.

Verdicts:

- `accepted` — the endpoint exists and the query validates
- `rejected` — the endpoint exists but the query uses something unsupported
- `rejected_as_expected` — the upstream test expects HTTP 400 and so do we
- `accepted_but_expected_error` — upstream expects HTTP 400, we accept the query
- `sibling:<entity>` — the query validates against a neighbouring entity; the upstream
  test file covers several entities, so the corpus label is too coarse
- `counts_filter` — an `event-counts` `counts_filter` expression that the extractor
  picked up as if it were a query
- `no_endpoint` / `root_needs_from` / `no_pql` — not routed, or not an AST query

`tests/unit/test_pdb_query_corpus.py` runs the same corpus as a regression test and
fails if acceptance drops below the recorded baseline.

## API differential comparison

`diff_api.py` runs the cases in `diff_cases.py` against pyppetdb and a real OpenVoxDB
holding the same data and compares the responses field by field.

```bash
venv/bin/python tests/conformance/diff_api.py \
  --ca ssl/certs/ca.pem --cert ssl/certs/client.crt --key ssl/private_keys/client.key \
  --a https://host:8001 --b https://host:8081 \
  --node some.node.example.com --verbose
```

Both targets must hold the same data. Either seed them with
`tests/benchmark/benchmark.py seed` using the same node count *and the same generation*,
or point them at a live Puppet infrastructure that feeds both.

List queries are paged: the tool asks both targets for `--page-size` rows (default 5000)
at a time with a stable `order_by` on the entity's natural key, fetches up to `--max-rows`
(default 50000) rows and compares those. With `--totals` it also asks for `include_total`
on the first page and compares the `X-Records` totals (`<total rows>`) — that is a
`count(*)` per paged case on both targets and takes minutes on the ten-million-row
subquery cases, so it is off by default. Paging also keeps the compared result sets
bounded: pyppetdb streams list responses without a limit, but refuses unpaged
`fact-contents`/`fact-paths` results above `app_puppetdb_maxPageSize` with a 400. Cases that carry their own
`limit`/`offset`/`order_by`, aggregates (`extract`/`function`/`group_by`) and the
`event-counts` routes are fetched as written. A truncated case prints `rows von total`.

The client certificate's CN must be listed in pyppetdb's `app_puppetdb_trustedCns`,
otherwise every `/pdb` call answers `403`.

### Cases

`diff_cases.py` holds 143 cases in nine groups, derived from what the rest of the suite
already covers. Each case records where it came from in its `origin`:

| origin | meaning |
| --- | --- |
| `integration` | mirrors a test in `tests/integration/test_pdb_query_api.py` |
| `unit` | a query shape exercised in `tests/unit/test_pdb_query_*.py` |
| `conformance` | a construct from the upstream corpus in `corpus/` |
| `review` | a case added for a specific bug or divergence found in review |
| `divergence` | a construct where pyppetdb and OpenVoxDB are known to disagree |

Every case is timed once by default. `--repeat N` runs each case N times, alternating between
the two targets, and reports the median; the rows compared are those of the last run. The console
then ends with the number of cases A answered faster and lists the others, so single outliers no
longer show up as regressions.

Select subsets with `--group <group-or-origin>` (repeatable) and `--only <regex>`:

```bash
# only the cases mirroring the integration suite
diff_api.py ... --group integration
# only subqueries and paging
diff_api.py ... --group subqueries --group paging
# the known divergences
diff_api.py ... --group divergences
```

Queries carry placeholders so the corpus is not tied to one data set:
`{node}` (`--node`), `{fact}` (`--fact`, default `kernel`), `{factvalue}`
(`--fact-value`, default `Linux`), `{type}` (`--type`, default `File`) and
`{environment}` (`--environment`, default `production`). Facter 4 has no `osfamily`
fact, so the defaults deliberately use facts that still exist.

Cases with `expect_error` pass when **both** sides answer `>= 400`; the report prints
the two status codes. A case reported as `identisch (leer)` compared two empty
results — it proves agreement but nothing about the data, and the summary line counts
these separately so a run over a thin data set does not read as full coverage.

### Known divergences

The `divergences` group documents constructs where OpenVoxDB rejects and pyppetdb
accepts. They are excluded from the default run and each is `expect_error`, so running
the group against pyppetdb reports exactly which ones we still accept:

- `["subquery", "facts", ...]` from `resources` — upstream's implicit relationships are
  not symmetric (`facts` <- `resources` works, the reverse does not); pyppetdb derives
  them symmetrically in `_build_relations`.
- `["extract", cols, ["from", entity, ...]]` — upstream only accepts the inverse nesting
  `["from", entity, ["extract", cols, ...]]`.
- `certname` on `/packages` — not a queryable column upstream.
- `/nodes/{certname}/reports` and `/nodes/{certname}/events` — routes do not exist
  upstream.
- `["from", "fact_names"]`, `["from", "producers"]`, `["from", "fact-names"]` and
  `["limit", 0]` — upstream answers `500` where pyppetdb answers a result or a `400`.

### Fields that are ignored, and order-independent collections

Some fields cannot match by construction and are dropped from the value comparison
entirely (a case that differs only in these still counts as identical), both at the top
level and nested inside catalog/report blobs:

- **hashes** (`hash`, `latest_report_hash`, `resource`, `report`, and the `href` of the
  child collections, which embeds a hash) — both sides compute them with different
  algorithms.
- **ingest timestamps** (`receive_time`, `report_receive_time`, `catalog_timestamp`,
  `facts_timestamp`, `report_timestamp`, `timestamp`) — they record when each system
  received the data.
- **PE-only fields** (`corrective_change`, `latest_report_corrective_change`) —
  OpenVoxDB stores these only when `store-corrective-change?` is enabled (a Puppet
  Enterprise setting, default off) and otherwise returns `null`, while pyppetdb keeps
  whatever the agent reported. The divergence is expected and not a pyppetdb bug.

Order-independent collections are compared as sets, not positionally:

- **tags** — both sides treat them as unordered (also normalised inside resource dicts).
- **child-collection `data` lists** (`edges`, `resources`, `resources_exported`,
  `inputs`, `facts`) — the embedded blobs list their members in different orders; each
  member is additionally stripped of the ignored fields above before comparison, so a
  differing `resource` hash or tag order does not register as a difference.

`producer_timestamp` is deliberately **not** ignored: it matches on catalogs (both take
the master's value) and only differs on factsets, which reflects a real detail of how
each system ingests facts — exactly the kind of thing the comparison should surface.
