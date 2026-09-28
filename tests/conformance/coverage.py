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

import asyncio
import json
import logging
import os
import sys
from collections import Counter
from collections import defaultdict
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
os.environ.setdefault("APP_SECRETKEY", "ci-test-secret")

from pyppetdb.controller.pdb import ControllerPdb  # noqa: E402
from pyppetdb.pdb.query.engine import QueryEngine  # noqa: E402
from pyppetdb.pdb.query.entities import get_entity  # noqa: E402
from pyppetdb.pdb.query.errors import PuppetDBQueryError  # noqa: E402
from pyppetdb.pdb.query.event_counts import COUNT_FIELDS  # noqa: E402

PATH_ENTITY = {
    "/pdb/query/v4/nodes": "nodes",
    "/pdb/query/v4/facts": "facts",
    "/pdb/query/v4/fact-names": "fact-names",
    "/pdb/query/v4/fact-paths": "fact-paths",
    "/pdb/query/v4/fact-contents": "fact-contents",
    "/pdb/query/v4/factsets": "factsets",
    "/pdb/query/v4/inventory": "inventory",
    "/pdb/query/v4/resources": "resources",
    "/pdb/query/v4/edges": "edges",
    "/pdb/query/v4/catalogs": "catalogs",
    "/pdb/query/v4/catalog-inputs": "catalog-inputs",
    "/pdb/query/v4/catalog-input-contents": "catalog-input-contents",
    "/pdb/query/v4/packages": "packages",
    "/pdb/query/v4/reports": "reports",
    "/pdb/query/v4/events": "events",
    "/pdb/query/v4/event-counts": "events",
    "/pdb/query/v4/aggregate-event-counts": "events",
    "/pdb/query/v4/environments": "environments",
    "/pdb/query/v4/producers": "producers",
}

SIBLING_ENTITIES = {
    "facts": ("fact-contents", "factsets", "fact-paths", "inventory"),
    "events": ("reports",),
    "reports": ("events",),
    "nodes": ("inventory", "factsets"),
}


def implemented_routes():
    controller = ControllerPdb(
        log=MagicMock(),
        config=MagicMock(),
        crud_nodes=MagicMock(),
        crud_nodes_catalog_cache=MagicMock(),
        crud_nodes_catalogs=MagicMock(),
        crud_nodes_groups=MagicMock(),
        crud_nodes_reports=MagicMock(),
        authorize_client_cert=MagicMock(),
        ingest_queue=MagicMock(),
    )
    routes = set()
    for route in controller.router.routes:
        for method in sorted(route.methods):
            routes.add((f"/pdb{route.path}", method))
    for route in controller.router_status.routes:
        for method in sorted(route.methods):
            routes.add((route.path, method))
    return routes


def load_corpus():
    rows = []
    with open(os.path.join(CORPUS, "openvoxdb_queries.json")) as handle:
        for entry in json.load(handle):
            rows.append({**entry, "origin": "openvoxdb-tests"})
    with open(os.path.join(CORPUS, "locust_queries.json")) as handle:
        for entry in json.load(handle):
            rows.append(
                {
                    **entry,
                    "origin": f"locust:{entry['consumer']}",
                    "expects_error": False,
                }
            )
    return rows


def entity_for(row):
    if row.get("pql") is not None:
        return None, "no_pql"
    if row["path"] == "/pdb/query/v4":
        query = row.get("query")
        if not isinstance(query, list) or not query or query[0] != "from":
            return None, "root_needs_from"
        entity = get_entity(query[1])
        return (entity.name if entity else None), (
            None if entity else "unknown_entity"
        )
    entity = PATH_ENTITY.get(row["path"])
    return entity, (None if entity else "no_endpoint")


async def evaluate(rows, routes):
    engine = QueryEngine(log=logging.getLogger("coverage"), collections={})
    results = []
    for row in rows:
        if (row["path"], row["method"]) not in routes:
            results.append({**row, "verdict": "no_endpoint", "reason": None})
            continue
        entity, problem = entity_for(row)
        if entity is None:
            results.append({**row, "verdict": problem, "reason": None})
            continue
        try:
            await engine.validate(entity, row.get("query"))
        except PuppetDBQueryError as err:
            if row.get("expects_error"):
                results.append(
                    {**row, "verdict": "rejected_as_expected", "reason": str(err)}
                )
                continue
            if _is_counts_filter(row):
                results.append(
                    {**row, "verdict": "counts_filter", "reason": None}
                )
                continue
            sibling = await _accepted_by_sibling(engine, entity, row.get("query"))
            if sibling:
                results.append(
                    {**row, "verdict": f"sibling:{sibling}", "reason": None}
                )
                continue
            results.append({**row, "verdict": "rejected", "reason": str(err)})
            continue
        except Exception as err:
            results.append(
                {**row, "verdict": "crash", "reason": f"{type(err).__name__}: {err}"}
            )
            continue
        verdict = "accepted_but_expected_error" if row.get("expects_error") else "accepted"
        results.append({**row, "verdict": verdict, "reason": None})
    return results


def _is_counts_filter(row) -> bool:
    if "event-counts" not in row["path"]:
        return False
    query = row.get("query")
    return (
        isinstance(query, list)
        and len(query) >= 2
        and isinstance(query[1], str)
        and query[1] in COUNT_FIELDS
    )


async def _accepted_by_sibling(engine, entity, query):
    for sibling in SIBLING_ENTITIES.get(entity, ()):
        try:
            await engine.validate(sibling, query)
            return sibling
        except PuppetDBQueryError:
            continue
        except Exception:
            continue
    return None


def report(results, routes):
    print(f"implemented /pdb routes: {len(routes)}")
    for path, method in sorted(routes):
        print(f"  {method:5} {path}")

    per_path = defaultdict(Counter)
    consumers = defaultdict(set)
    reasons = Counter()
    for row in results:
        per_path[row["path"]][row["verdict"]] += 1
        if row["origin"].startswith("locust:"):
            consumers[row["path"]].add(row["origin"].split(":", 1)[1])
        if row["verdict"] in ("rejected", "crash"):
            reasons[row["reason"][:110]] += 1

    print(f"\n{'endpoint':40} {'total':>6}  breakdown")
    for path in sorted(per_path, key=lambda item: -sum(per_path[item].values())):
        counts = per_path[path]
        breakdown = ", ".join(f"{key}={value}" for key, value in counts.most_common())
        suffix = f"  [{', '.join(sorted(consumers[path]))}]" if consumers[path] else ""
        print(f"{path:40} {sum(counts.values()):6d}  {breakdown}{suffix}")

    if reasons:
        print("\nunsupported constructs:")
        for reason, count in reasons.most_common(20):
            print(f"  {count:4d}  {reason}")

    print("\ntotals:", dict(Counter(row["verdict"] for row in results)))


async def main():
    routes = implemented_routes()
    results = await evaluate(load_corpus(), routes)
    with open(os.path.join(HERE, "coverage.json"), "w") as handle:
        json.dump(results, handle, indent=1)
    report(results, routes)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
