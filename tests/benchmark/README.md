# pyppetdb vs OpenVoxDB benchmark

Runs the same PuppetDB workload against pyppetdb and against a real OpenVoxDB, on
identical data, over HTTPS with the same client certificate.

Both targets are loaded exclusively through `/pdb/cmd/v1` with genuine PuppetDB wire
format, so the seeding path itself is a compatibility test: whatever OpenVoxDB accepts,
pyppetdb has to accept too.

## Setup

```bash
# 1. certificates shared by both targets
tests/benchmark/gen_certs.sh /tmp/benchcerts

# 2. OpenVoxDB + PostgreSQL, listening on https://localhost:18081 with mTLS
export BENCH_CERTS=/tmp/benchcerts
docker compose -f tests/benchmark/docker-compose.yml up -d

# 3. pyppetdb with the upstream backend switched off
export app_main_port=18000
export app_main_ssl_ca=$BENCH_CERTS/ca.pem
export app_main_ssl_cert=$BENCH_CERTS/server.crt
export app_main_ssl_key=$BENCH_CERTS/server.key
export app_puppetdb_trustedCns='["bench-client"]'
export app_puppetdb_querySource=internal
export ca_verifyCertificateRegistration=false
export mongodb_database=pyppetdb_bench
unset app_puppetdb_serverurl
venv/bin/pyppetdb
```

`app_puppetdb_serverurl` must stay unset so pyppetdb answers from its own store and does
not forward anything upstream — otherwise the benchmark measures both systems at once.

## Running

```bash
CERTS="--ca /tmp/benchcerts/ca.pem --cert /tmp/benchcerts/client.crt --key /tmp/benchcerts/client.key"

# load the same generated dataset into both targets
venv/bin/python tests/benchmark/benchmark.py $CERTS --nodes 300 --concurrency 4 \
  seed --target https://localhost:18000
venv/bin/python tests/benchmark/benchmark.py $CERTS --nodes 300 --concurrency 1 \
  seed --target https://localhost:18081

# compare
venv/bin/python tests/benchmark/benchmark.py $CERTS --nodes 300 \
  --iterations 25 --concurrency 1 --json /tmp/bench.json \
  compare --a https://localhost:18000 --name-a pyppetdb \
          --b https://localhost:18081 --name-b openvoxdb
```

Seed OpenVoxDB with `--concurrency 1`. Concurrent catalog ingest makes PuppetDB collide
on the shared `resource_params_cache` primary key; it schedules retries with a long
backoff and the affected catalogs stay missing for the rest of the run.

`compare` prints a dataset cross-check before the timings. Only trust the latencies when
the row counts agree — otherwise the two targets are not doing the same work.

## Write load

`write` (one target) and `compare-write` (two targets) measure command ingest:

```bash
venv/bin/python tests/benchmark/benchmark.py $CERTS --nodes 300 --concurrency 8 \
  compare-write --a https://localhost:18000 --name-a pyppetdb \
                --b https://localhost:18081 --name-b openvoxdb
```

Both systems acknowledge commands asynchronously — pyppetdb hands the work to an
`asyncio` task, PuppetDB writes to its stockpile queue — so HTTP latency alone says
nothing about storage cost. Two numbers are therefore reported per command:

- **accept p50/p99** — what the agent waits for.
- **settled** — wall clock from the first submit until every command is queryable, and
  the resulting `cmd/s` and `units/s`. This is the honest ingest capacity.

To make writes observable, each payload carries a generation marker: a `bench_generation`
fact, the catalog `version`, and the report `configuration_version`. The tool polls the
matching entity until all `--nodes` commands are visible. Use `--commands` to restrict
the run and `--generation` to pin the marker.

The nodes should already exist, so that the run measures a *replace* rather than a first
insert. Seed first.

**Durability is not equal.** PuppetDB acknowledges only after the command is durably
queued and survives a crash; pyppetdb acknowledges after scheduling the write. Part of
pyppetdb's lower accept latency is a weaker promise, not just more speed.

At a concurrency high enough to saturate both, OpenVoxDB settles at a uniform ceiling
across all command types (its queue drain rate), while pyppetdb's throughput depends
strongly on the command: facts and reports are well ahead, catalogs fall behind and
degrade as concurrency rises, because normalising 200 resources and validating them
through Pydantic is CPU-bound work on a single event loop.

## What is measured

`workload.py` generates deterministic nodes (150 facts including structured ones, 200
catalog resources, 40 report resources with events) and defines 20 query classes:
point lookups, fact and resource scans, dotted parameter and fact access, a cross-entity
subquery, aggregation with `group_by`/`count`, event counts, and a paged query with
`include_total`.

Timestamps are anchored to the current hour, so both targets get identical data as long
as they are seeded within the same hour. This matters: PuppetDB partitions
`resource_events` by time and silently drops events whose timestamp falls outside the
retained window, so a fixed historical date yields zero events upstream.

Latencies are reported per query class as p50/p90/p99 in milliseconds. Run with
`--concurrency 1` for per-request latency and with a higher value to see how each server
behaves under load.

## Known differences

- OpenVoxDB reports 4 more events per node than pyppetdb: it synthesises a `skipped`
  event for every skipped resource, pyppetdb only stores events the agent actually sent.
- pyppetdb accepts report events without `corrective_change`; OpenVoxDB rejects the whole
  command.
