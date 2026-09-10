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

import json
import logging
import os
import unittest

from pyppetdb.pdbquery.engine import QueryEngine
from pyppetdb.pdbquery.errors import PuppetDBQueryError

CORPUS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "conformance",
    "corpus",
)

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

ACCEPTED_BASELINE = 431


def load_corpus():
    entries = []
    with open(os.path.join(CORPUS_DIR, "openvoxdb_queries.json")) as handle:
        entries.extend(json.load(handle))
    with open(os.path.join(CORPUS_DIR, "locust_queries.json")) as handle:
        for entry in json.load(handle):
            entries.append({**entry, "expects_error": False})
    return entries


def entity_for(entry):
    if entry.get("pql") is not None:
        return None
    query = entry.get("query")
    if entry["path"] == "/pdb/query/v4":
        if isinstance(query, list) and query and query[0] == "from":
            return query[1]
        return None
    return PATH_ENTITY.get(entry["path"])


class TestConformanceCorpus(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()

    def setUp(self):
        self.engine = QueryEngine(log=logging.getLogger("test"), collections={})

    async def test_corpus_is_present(self):
        self.assertGreater(len(self.corpus), 500)

    async def test_no_query_crashes_the_engine(self):
        for entry in self.corpus:
            entity = entity_for(entry)
            if entity is None:
                continue
            try:
                await self.engine.validate(entity, entry.get("query"))
            except PuppetDBQueryError:
                continue
            except Exception as err:
                self.fail(
                    f"{type(err).__name__} for {entry['path']} "
                    f"{json.dumps(entry.get('query'))}: {err}"
                )

    async def test_accepted_query_count_does_not_regress(self):
        accepted = 0
        for entry in self.corpus:
            entity = entity_for(entry)
            if entity is None:
                continue
            try:
                await self.engine.validate(entity, entry.get("query"))
            except PuppetDBQueryError:
                continue
            accepted += 1
        self.assertGreaterEqual(
            accepted,
            ACCEPTED_BASELINE,
            f"corpus acceptance regressed to {accepted}",
        )

    async def test_locust_consumer_queries_are_accepted(self):
        rejected = []
        for entry in self.corpus:
            if not entry.get("consumer"):
                continue
            entity = entity_for(entry)
            if entity is None:
                rejected.append((entry["alias"], "no route"))
                continue
            try:
                await self.engine.validate(entity, entry.get("query"))
            except PuppetDBQueryError as err:
                rejected.append((entry["alias"], str(err)))
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
