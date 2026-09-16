# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from tests.benchmark import workload  # noqa: E402
from tests.benchmark.runner import Target  # noqa: E402
from tests.benchmark.runner import Timing  # noqa: E402
from tests.benchmark.runner import measure  # noqa: E402
from tests.benchmark.runner import run_query  # noqa: E402
from tests.benchmark.runner import send_command  # noqa: E402
from tests.benchmark.runner import wait_for  # noqa: E402

SEED_RETRY_ATTEMPTS = 20
SEED_RETRY_MAX_SLEEP = 5.0


def make_target(name: str, url: str, args) -> Target:
    return Target(
        name=name,
        base_url=url,
        ca=args.ca,
        cert=args.cert,
        key=args.key,
        concurrency=args.concurrency,
    )


async def seed(target: Target, nodes: int, seed_value: int, concurrency: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    failures = []
    retries = []

    async def one(index: int, command: str, version: int, builder):
        async with semaphore:
            name = workload.certname(index)
            payload = builder(index, seed_value)
            for _attempt in range(SEED_RETRY_ATTEMPTS):
                response = await send_command(
                    target, name, command, version, payload
                )
                if response.status_code != 503:
                    break
                retries.append(name)
                retry_after = response.headers.get("retry-after") or "1"
                await asyncio.sleep(min(float(retry_after), SEED_RETRY_MAX_SLEEP))
            if response.status_code not in (200, 201):
                failures.append(
                    (name, command, response.status_code, response.text[:200])
                )

    started = time.perf_counter()
    for command, version, builder in workload.COMMANDS:
        await asyncio.gather(
            *(one(index, command, version, builder) for index in range(nodes))
        )
        await wait_for_ingest(target, nodes)
    elapsed = time.perf_counter() - started
    return {"seconds": elapsed, "failures": failures, "retries": len(retries)}


COUNT_ENTITIES = ("nodes", "facts", "resources", "reports", "events")


async def entity_counts(target: Target) -> dict:
    counts = {}
    for entity in COUNT_ENTITIES:
        spec = {
            "name": f"count_{entity}",
            "path": "/pdb/query/v4",
            "ast": ["from", entity, ["extract", [["function", "count"]]]],
            "params": {},
        }
        try:
            response = await run_query(target, spec)
            body = response.json() if response.status_code == 200 else []
            counts[entity] = body[0].get("count", 0) if body else 0
        except Exception:
            counts[entity] = -1
    return counts


async def wait_for_ingest(target: Target, expected: int, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    previous = None
    while time.time() < deadline:
        counts = await entity_counts(target)
        if counts.get("nodes", 0) >= expected and counts == previous:
            return counts
        previous = counts
        await asyncio.sleep(3.0)
    return previous or {}


async def count_matching(target: Target, entity: str, ast) -> int:
    spec = {
        "name": "probe",
        "path": "/pdb/query/v4",
        "ast": ["from", entity, ["extract", [["function", "count"]], ast]],
        "params": {},
    }
    response = await run_query(target, spec)
    if response.status_code != 200:
        return -1
    body = response.json()
    return body[0].get("count", 0) if body else 0


async def write_round(
    target: Target,
    command: str,
    version: int,
    builder,
    nodes: int,
    seed_value: int,
    generation: int,
    concurrency: int,
    settle_timeout: float = 900.0,
) -> dict:
    probe = workload.WRITE_PROBES[command]
    since = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    timing = Timing(command)
    semaphore = asyncio.Semaphore(concurrency)
    rejected = []

    async def one(index: int):
        async with semaphore:
            payload = builder(index, seed_value, generation=generation)
            started = time.perf_counter()
            try:
                response = await send_command(
                    target, workload.certname(index), command, version, payload
                )
            except Exception as err:
                rejected.append(("transport", repr(err)[:120]))
                return
            elapsed = time.perf_counter() - started
            if response.status_code not in (200, 201):
                rejected.append((response.status_code, response.text[:120]))
                return
            timing.add(elapsed)

    submit_started = time.perf_counter()
    await asyncio.gather(*(one(index) for index in range(nodes)))
    submit_seconds = time.perf_counter() - submit_started

    expected = nodes - len(rejected)
    query = probe["query"](generation, since)
    deadline = time.time() + settle_timeout
    visible = 0
    while time.time() < deadline and expected:
        visible = await count_matching(target, probe["entity"], query)
        if visible >= expected:
            break
        await asyncio.sleep(0.25)
    settle_seconds = time.perf_counter() - submit_started

    summary = timing.summary()
    summary.update(
        {
            "command": command,
            "submitted": nodes,
            "visible": visible,
            "rejected": len(rejected),
            "rejections": rejected[:3],
            "submit_seconds": submit_seconds,
            "settle_seconds": settle_seconds,
            "commands_per_second": (
                (nodes - len(rejected)) / settle_seconds if settle_seconds else 0.0
            ),
            "units_per_second": (
                (nodes - len(rejected)) * probe["per_command"] / settle_seconds
                if settle_seconds
                else 0.0
            ),
            "unit": probe["unit"],
        }
    )
    return summary


async def run_writes(target: Target, args, generation: int) -> list:
    selected = set((args.commands or "").split(",")) if args.commands else None
    results = []
    for offset, (command, version, builder) in enumerate(workload.COMMANDS):
        if selected and command not in selected:
            continue
        results.append(
            await write_round(
                target=target,
                command=command,
                version=version,
                builder=builder,
                nodes=args.nodes,
                seed_value=args.seed,
                generation=generation + offset,
                concurrency=args.concurrency,
            )
        )
    return results


def print_writes(name: str, results: list) -> None:
    print(f"\n{name}")
    header = (
        f"{'command':18} {'n':>5} {'accept p50':>11} {'accept p99':>11} "
        f"{'submit':>8} {'settled':>9} {'cmd/s':>8} {'units/s':>10} {'err':>4}"
    )
    print(header)
    print("-" * len(header))
    for row in results:
        accept50 = f"{row['p50']:.1f}ms" if row.get("n") else "-"
        accept99 = f"{row['p99']:.1f}ms" if row.get("n") else "-"
        print(
            f"{row['command']:18} {row['submitted']:5d} {accept50:>11} {accept99:>11} "
            f"{row['submit_seconds']:7.2f}s {row['settle_seconds']:8.2f}s "
            f"{row['commands_per_second']:8.1f} {row['units_per_second']:10.0f} "
            f"{row['rejected']:4d}"
        )
        accepted = row["submitted"] - row["rejected"]
        if row["rejected"]:
            print(
                f"{'':18} {row['rejected']}/{row['submitted']} rejected by the target "
                "(backpressure)"
            )
        if row["visible"] < accepted:
            print(
                f"{'':18} only {row['visible']}/{accepted} accepted commands became "
                "queryable within the timeout"
            )
        for rejection in row["rejections"]:
            print(f"{'':18} rejected: {rejection}")


def print_write_comparison(name_a, results_a, name_b, results_b) -> None:
    by_name = {row["command"]: row for row in results_b}
    header = (
        f"{'command':18} {name_a[:9]+' accept':>17} {name_b[:9]+' accept':>17} "
        f"{name_a[:9]+' cmd/s':>16} {name_b[:9]+' cmd/s':>16} {'ratio':>7}"
    )
    print()
    print(header)
    print("-" * len(header))
    for row_a in results_a:
        row_b = by_name.get(row_a["command"])
        if not row_b:
            continue
        ratio = (
            row_b["commands_per_second"] / row_a["commands_per_second"]
            if row_a["commands_per_second"]
            else 0.0
        )
        accept_a = f"{row_a['p50']:.1f}ms" if row_a.get("n") else "-"
        accept_b = f"{row_b['p50']:.1f}ms" if row_b.get("n") else "-"
        verdict = f"{ratio:.2f}x"
        print(
            f"{row_a['command']:18} {accept_a:>17} {accept_b:>17} "
            f"{row_a['commands_per_second']:16.1f} {row_b['commands_per_second']:16.1f} "
            f"{verdict:>7}"
        )
    print("\nratio > 1 means the second target ingests faster")


async def run_queries(target: Target, specs: list, iterations: int, concurrency: int):
    results = []
    for spec in specs:
        timing = await measure(target, spec, iterations, concurrency)
        results.append(timing.summary())
    return results


def print_single(name: str, results: list) -> None:
    print(f"\n{name}")
    header = f"{'query':30} {'n':>4} {'rows':>7} {'p50':>9} {'p90':>9} {'p99':>9} {'err':>4}"
    print(header)
    print("-" * len(header))
    for row in results:
        if not row["n"]:
            print(f"{row['name']:30} {0:4d} {'-':>7} {'-':>9} {'-':>9} {'-':>9} {row['errors']:4d}")
            continue
        print(
            f"{row['name']:30} {row['n']:4d} {str(row['rows']):>7} "
            f"{row['p50']:9.2f} {row['p90']:9.2f} {row['p99']:9.2f} {row['errors']:4d}"
        )


def print_comparison(name_a: str, results_a: list, name_b: str, results_b: list) -> None:
    by_name_b = {row["name"]: row for row in results_b}
    header = (
        f"{'query':30} {'rows A':>7} {'rows B':>7} "
        f"{name_a[:9]+' p50':>13} {name_b[:9]+' p50':>13} {'ratio':>8} {'verdict':>9}"
    )
    print()
    print(header)
    print("-" * len(header))
    for row_a in results_a:
        row_b = by_name_b.get(row_a["name"])
        if not row_a["n"] or not row_b or not row_b["n"]:
            print(f"{row_a['name']:30} {'-':>7} {'-':>7} {'error':>13} {'error':>13} {'-':>8} {'-':>9}")
            continue
        ratio = row_a["p50"] / row_b["p50"] if row_b["p50"] else 0.0
        verdict = "A faster" if ratio < 1 else "B faster"
        rows_match = "" if row_a["rows"] == row_b["rows"] else "  <-- row count differs"
        print(
            f"{row_a['name']:30} {str(row_a['rows']):>7} {str(row_b['rows']):>7} "
            f"{row_a['p50']:13.2f} {row_b['p50']:13.2f} {ratio:8.2f} {verdict:>9}{rows_match}"
        )


async def command_seed(args) -> int:
    async with make_target("target", args.target, args) as target:
        await wait_for(target, "/pdb/query/v4/environments")
        print(f"seeding {args.nodes} nodes into {args.target} ...")
        result = await seed(target, args.nodes, args.seed, args.concurrency)
        print(f"submitted in {result['seconds']:.1f}s")
        for failure in result["failures"][:5]:
            print(f"  FAILED {failure}")
        if result["failures"]:
            print(f"  {len(result['failures'])} node(s) failed")
        if result.get("retries"):
            print(f"  {result['retries']} command(s) retried after 503")
        print("waiting until ingest has settled ...")
        started = time.perf_counter()
        counts = await wait_for_ingest(target, args.nodes)
        print(f"settled after {time.perf_counter() - started:.1f}s")
        print("  " + "  ".join(f"{key}={value}" for key, value in counts.items()))
        return 0 if counts.get("nodes", 0) >= args.nodes else 1


async def command_query(args) -> int:
    specs = workload.build_queries(args.nodes)
    if args.only:
        specs = [spec for spec in specs if spec["name"] in set(args.only.split(","))]
    async with make_target("target", args.target, args) as target:
        results = await run_queries(target, specs, args.iterations, args.concurrency)
    print_single(args.target, results)
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(results, handle, indent=1)
    return 0


async def command_compare(args) -> int:
    specs = workload.build_queries(args.nodes)

    if args.only:
        specs = [spec for spec in specs if spec["name"] in set(args.only.split(","))]

    async with make_target(args.name_a, args.a, args) as target_a:
        counts_a = await entity_counts(target_a)
        results_a = await run_queries(target_a, specs, args.iterations, args.concurrency)
    async with make_target(args.name_b, args.b, args) as target_b:
        counts_b = await entity_counts(target_b)
        results_b = await run_queries(target_b, specs, args.iterations, args.concurrency)

    print("\ndataset")
    print(f"{'entity':12} {args.name_a:>14} {args.name_b:>14}")
    for entity in COUNT_ENTITIES:
        marker = "" if counts_a.get(entity) == counts_b.get(entity) else "   <-- differs"
        print(f"{entity:12} {counts_a.get(entity, -1):14d} {counts_b.get(entity, -1):14d}{marker}")

    print_single(f"{args.name_a}  ({args.a})", results_a)
    print_single(f"{args.name_b}  ({args.b})", results_b)
    print_comparison(args.name_a, results_a, args.name_b, results_b)

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(
                {
                    args.name_a: results_a,
                    args.name_b: results_b,
                    "config": {
                        "nodes": args.nodes,
                        "iterations": args.iterations,
                        "concurrency": args.concurrency,
                    },
                },
                handle,
                indent=1,
            )
    return 0


async def command_write(args) -> int:
    generation = args.generation or int(time.time()) % 100000
    async with make_target("target", args.target, args) as target:
        results = await run_writes(target, args, generation)
    print_writes(args.target, results)
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(results, handle, indent=1)
    return 0


async def command_compare_write(args) -> int:
    generation = args.generation or int(time.time()) % 100000
    async with make_target(args.name_a, args.a, args) as target_a:
        results_a = await run_writes(target_a, args, generation)
    async with make_target(args.name_b, args.b, args) as target_b:
        results_b = await run_writes(target_b, args, generation + 100)

    print_writes(f"{args.name_a}  ({args.a})", results_a)
    print_writes(f"{args.name_b}  ({args.b})", results_b)
    print_write_comparison(args.name_a, results_a, args.name_b, results_b)

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(
                {
                    args.name_a: results_a,
                    args.name_b: results_b,
                    "config": {
                        "nodes": args.nodes,
                        "concurrency": args.concurrency,
                    },
                },
                handle,
                indent=1,
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the pyppetdb PuppetDB API against a real OpenVoxDB"
    )
    parser.add_argument("--ca")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--nodes", type=int, default=200)
    parser.add_argument("--resources-per-node", type=int, default=None)
    parser.add_argument("--facts-file", default=None)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--only")
    parser.add_argument("--commands")
    parser.add_argument("--generation", type=int)
    parser.add_argument("--json")

    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="load generated nodes into one target")
    seed_parser.add_argument("--target", required=True)
    seed_parser.set_defaults(func=command_seed)

    query_parser = sub.add_parser("query", help="run the read workload against one target")
    query_parser.add_argument("--target", required=True)
    query_parser.set_defaults(func=command_query)

    write_parser = sub.add_parser(
        "write", help="measure command ingest against one target"
    )
    write_parser.add_argument("--target", required=True)
    write_parser.set_defaults(func=command_write)

    compare_write_parser = sub.add_parser(
        "compare-write", help="measure command ingest against two targets"
    )
    compare_write_parser.add_argument("--a", required=True)
    compare_write_parser.add_argument("--b", required=True)
    compare_write_parser.add_argument("--name-a", default="A")
    compare_write_parser.add_argument("--name-b", default="B")
    compare_write_parser.set_defaults(func=command_compare_write)

    compare_parser = sub.add_parser("compare", help="run the read workload against two targets")
    compare_parser.add_argument("--a", required=True)
    compare_parser.add_argument("--b", required=True)
    compare_parser.add_argument("--name-a", default="A")
    compare_parser.add_argument("--name-b", default="B")
    compare_parser.set_defaults(func=command_compare)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "resources_per_node", None):
        workload.RESOURCE_COUNT = args.resources_per_node
    if args.facts_file:
        workload.load_real_facts(args.facts_file)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
