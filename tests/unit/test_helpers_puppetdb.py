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

import unittest
from datetime import datetime

from pyppetdb.helpers.puppetdb import catalog_metadata
from pyppetdb.helpers.puppetdb import catalog_payload
from pyppetdb.helpers.puppetdb import normalise_catalog_inputs
from pyppetdb.helpers.puppetdb import build_facts_index
from pyppetdb.helpers.puppetdb import build_resource_params
from pyppetdb.helpers.puppetdb import normalise_edges
from pyppetdb.model.nodes import NodeGetCatalog
from pyppetdb.helpers.puppetdb import normalise_package_inventory
from pyppetdb.helpers.puppetdb import normalise_resources
from pyppetdb.helpers.puppetdb import parse_wire_timestamp
from pyppetdb.helpers.puppetdb import report_payload
from pyppetdb.helpers.puppetdb import resource_hash
from pyppetdb.helpers.puppetdb import stable_hash


class TestHashes(unittest.TestCase):
    def test_stable_hash_is_order_independent(self):
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

    def test_resource_hash_distinguishes_type_and_title(self):
        self.assertNotEqual(resource_hash("File", "a"), resource_hash("File", "b"))
        self.assertNotEqual(resource_hash("File", "a"), resource_hash("Exec", "a"))


class TestTimestamps(unittest.TestCase):
    def test_parses_zulu(self):
        parsed = parse_wire_timestamp("2026-03-24T09:30:23.308Z")
        self.assertIsInstance(parsed, datetime)
        self.assertIsNotNone(parsed.tzinfo)

    def test_returns_none_for_garbage(self):
        self.assertIsNone(parse_wire_timestamp("not a time"))
        self.assertIsNone(parse_wire_timestamp(None))


class TestNormalisers(unittest.TestCase):
    def test_resources_get_hash_and_defaults(self):
        resources = normalise_resources(
            [{"type": "File", "title": "/tmp/x", "file": "init.pp", "line": 3}]
        )
        self.assertEqual(resources[0]["resource"], resource_hash("File", "/tmp/x"))
        self.assertEqual(resources[0]["tags"], [])
        self.assertEqual(resources[0]["parameters"], {})
        self.assertIs(resources[0]["exported"], False)
        self.assertEqual(resources[0]["file"], "init.pp")
        self.assertEqual(resources[0]["line"], 3)

    def test_edges_are_flattened(self):
        edges = normalise_edges(
            [
                {
                    "source": {"type": "Stage", "title": "main"},
                    "target": {"type": "Class", "title": "Settings"},
                    "relationship": "contains",
                }
            ]
        )
        self.assertEqual(
            edges,
            [
                {
                    "relationship": "contains",
                    "source_type": "Stage",
                    "source_title": "main",
                    "target_type": "Class",
                    "target_title": "Settings",
                }
            ],
        )

    def test_package_inventory(self):
        self.assertEqual(
            normalise_package_inventory([["vim", "9.0", "apt"], ["bad"]]),
            [["vim", "9.0", "apt"]],
        )
        self.assertIsNone(normalise_package_inventory(None))

    def test_catalog_inputs(self):
        self.assertEqual(
            normalise_catalog_inputs([["hiera", "key"], "junk"]), [["hiera", "key"]]
        )


class TestResourceParams(unittest.TestCase):
    def test_normalises_and_deduplicates(self):
        resources = [
            {"resource": "h1", "parameters": {"ensure": "present", "mode": "0644"}},
            {"resource": "h2", "parameters": {"ensure": "present"}},
        ]
        pairs = build_resource_params(resources)
        self.assertIn({"n": "ensure", "v": "present"}, pairs)
        self.assertIn({"n": "mode", "v": "0644"}, pairs)
        # dedupliziert ueber resources hinweg
        self.assertEqual(sum(1 for p in pairs if p["n"] == "ensure"), 1)

    def test_excludes_large_and_complex_values(self):
        resources = [{"resource": "h1", "parameters": {
            "content": "x" * 600,
            "meta": {"a": 1},
            "list": [1, 2],
            "count": 3,
            "flag": True,
        }}]
        pairs = build_resource_params(resources)
        names = {p["n"] for p in pairs}
        self.assertNotIn("content", names)
        self.assertNotIn("meta", names)
        self.assertNotIn("list", names)
        self.assertIn("count", names)
        self.assertIn("flag", names)


class TestFactsIndex(unittest.TestCase):
    def paths(self, entries):
        return [entry["p"] for entry in entries]

    def values(self, entries):
        return {
            (entry["p"], entry["v"]) for entry in entries if "v" in entry
        }

    def test_each_top_level_fact_costs_one_entry(self):
        facts = {f"f{index}": f"value{index}" for index in range(20)}
        facts["structured"] = {"a": 1}
        self.assertEqual(len(build_facts_index(facts, depth=1)), 21)
        self.assertEqual(len(build_facts_index(facts)), 22)

    def test_every_top_level_key_is_listed_by_name(self):
        entries = build_facts_index(
            {
                "osfamily": "Debian",
                "os": {"family": "Debian"},
                "secret": "s3cr3t",
                "huge": "x" * 300,
            },
            deny=["secret"],
            depth=1,
        )
        self.assertEqual(
            sorted(set(self.paths(entries))),
            ["huge", "os", "osfamily", "secret"],
        )
        self.assertEqual(self.values(entries), {("osfamily", "Debian")})

    def test_an_indexable_scalar_yields_exactly_one_entry(self):
        self.assertEqual(
            build_facts_index({"osfamily": "Debian"}),
            [{"p": "osfamily", "v": "Debian"}],
        )

    def test_a_list_fact_is_named_by_its_element_entries(self):
        self.assertEqual(
            build_facts_index({"roles": ["web", "db"]}),
            [{"p": "roles", "v": "web"}, {"p": "roles", "v": "db"}],
        )

    def test_a_list_without_indexable_elements_keeps_a_bare_entry(self):
        self.assertEqual(build_facts_index({"roles": []}), [{"p": "roles"}])
        self.assertEqual(
            build_facts_index({"ifaces": [{"name": "eth0"}]}, depth=1),
            [{"p": "ifaces"}],
        )

    def test_structured_and_denied_facts_keep_a_bare_entry(self):
        entries = build_facts_index(
            {"os": {"family": "Debian"}, "role": "web"}, deny=["role"], depth=1
        )
        self.assertIn({"p": "os"}, entries)
        self.assertIn({"p": "role"}, entries)
        self.assertEqual(self.values(entries), set())

    def test_value_length_boundary(self):
        exact = build_facts_index({"a": "x" * 8}, max_value_len=8)
        too_long = build_facts_index({"a": "x" * 9}, max_value_len=8)
        self.assertEqual(self.values(exact), {("a", "x" * 8)})
        self.assertEqual(self.values(too_long), set())

    def test_scalars_of_every_type_are_indexed(self):
        entries = build_facts_index(
            {"b": True, "i": 7, "f": 1.5, "s": "x", "n": None}
        )
        self.assertEqual(
            self.values(entries),
            {("b", True), ("i", 7), ("f", 1.5), ("s", "x")},
        )

    def test_depth_one_ignores_nested_leaves(self):
        entries = build_facts_index({"os": {"family": "Debian"}}, depth=1)
        self.assertEqual(self.values(entries), set())

    def test_depth_two_emits_dotted_paths(self):
        entries = build_facts_index(
            {"os": {"family": "Debian", "release": {"major": "12"}}}, depth=2
        )
        self.assertEqual(self.values(entries), {("os.family", "Debian")})
        self.assertEqual(
            entries, [{"p": "os"}, {"p": "os.family", "v": "Debian"}]
        )

    def test_depth_three_reaches_deeper_leaves(self):
        entries = build_facts_index(
            {"os": {"release": {"major": "12"}}}, depth=3
        )
        self.assertEqual(self.values(entries), {("os.release.major", "12")})

    def test_lists_do_not_consume_a_depth_level(self):
        entries = build_facts_index(
            {"ifaces": [{"name": "eth0"}, "eth1"]}, depth=1
        )
        self.assertEqual(self.values(entries), {("ifaces", "eth1")})
        entries = build_facts_index(
            {"ifaces": [{"name": "eth0"}, "eth1"]}, depth=2
        )
        self.assertEqual(
            self.values(entries),
            {("ifaces", "eth1"), ("ifaces.name", "eth0")},
        )

    def test_positional_and_unsafe_paths_are_not_value_indexed(self):
        entries = build_facts_index({"0day": "yes", "we ird": "x"})
        self.assertEqual(sorted(set(self.paths(entries))), ["0day", "we ird"])
        self.assertEqual(self.values(entries), set())

    def test_scalar_list_elements_are_indexed(self):
        entries = build_facts_index({"roles": ["web", "db", "web"]})
        self.assertEqual(
            self.values(entries), {("roles", "web"), ("roles", "db")}
        )

    def test_deny_matches_exact_name_and_prefix(self):
        entries = build_facts_index(
            {"os": {"family": "Debian"}, "uptime": 5},
            depth=2,
            deny=["os", "uptime"],
        )
        self.assertEqual(self.values(entries), set())
        entries = build_facts_index(
            {"os": {"family": "Debian"}}, depth=2, deny=["os.family"]
        )
        self.assertEqual(self.values(entries), set())

    def test_non_dict_facts_yield_nothing(self):
        self.assertEqual(build_facts_index(None), [])
        self.assertEqual(build_facts_index(["a"]), [])


class TestPayloads(unittest.TestCase):
    catalog = {
        "certname": "host1",
        "catalog_uuid": "cu",
        "version": 12,
        "transaction_uuid": "tu",
        "code_id": "ci",
        "producer": "pm1",
        "producer_timestamp": "2026-03-24T09:30:23Z",
        "resources": [
            {"type": "File", "title": "a", "exported": True},
            {"type": "File", "title": "b"},
        ],
        "edges": [
            {
                "source": {"type": "Stage", "title": "main"},
                "target": {"type": "Class", "title": "S"},
                "relationship": "contains",
            }
        ],
    }

    def test_catalog_payload(self):
        payload = catalog_payload(self.catalog)
        self.assertEqual(payload["num_resources"], 2)
        self.assertEqual(payload["num_resources_exported"], 1)
        self.assertEqual(payload["version"], "12")
        self.assertEqual(len(payload["edges"]), 1)
        self.assertIsInstance(payload["producer_timestamp"], datetime)
        self.assertTrue(payload["hash"])

    def test_model_preserves_resource_and_edge_detail(self):
        detailed = dict(
            self.catalog,
            resources=[
                {
                    "type": "File",
                    "title": "/tmp/x",
                    "file": "/etc/site.pp",
                    "line": 42,
                    "exported": False,
                    "tags": ["t"],
                    "parameters": {"ensure": "present"},
                }
            ],
        )
        stored = NodeGetCatalog(**catalog_payload(detailed)).model_dump()
        resource = stored["resources"][0]
        self.assertEqual(resource["file"], "/etc/site.pp")
        self.assertEqual(resource["line"], 42)
        self.assertTrue(resource["resource"])
        self.assertEqual(len(stored["edges"]), 1)
        self.assertEqual(stored["edges"][0]["relationship"], "contains")
        self.assertEqual(stored["edges"][0]["source_type"], "Stage")
        self.assertEqual(stored["version"], "12")
        self.assertEqual(stored["transaction_uuid"], "tu")
        self.assertEqual(stored["producer"], "pm1")
        self.assertIsNotNone(stored["producer_timestamp"])

    def test_catalog_hash_changes_with_resources(self):
        other = dict(self.catalog, resources=[{"type": "File", "title": "a"}])
        self.assertNotEqual(
            catalog_payload(self.catalog)["hash"], catalog_payload(other)["hash"]
        )

    def test_report_payload_fills_optional_fields(self):
        payload = report_payload({"certname": "host1", "status": "changed"})
        self.assertEqual(payload["status"], "changed")
        self.assertEqual(payload["logs"], [])
        self.assertEqual(payload["metrics"], [])
        self.assertEqual(payload["resources"], [])
        self.assertIs(payload["latest"], True)
        self.assertTrue(payload["hash"])

    def test_report_payload_parses_times(self):
        payload = report_payload(
            {
                "certname": "host1",
                "start_time": "2026-03-24T09:00:00Z",
                "end_time": "2026-03-24T09:01:00Z",
                "configuration_version": 1234,
            }
        )
        self.assertIsInstance(payload["start_time"], datetime)
        self.assertEqual(payload["configuration_version"], "1234")


class TestCatalogMetadata(unittest.TestCase):
    def test_drops_only_the_content_fields(self):
        payload = catalog_payload(
            {
                "certname": "host1",
                "catalog_uuid": "uuid1",
                "version": 4711,
                "transaction_uuid": "tx1",
                "code_id": "code1",
                "job_id": 5,
                "producer": "pm1",
                "producer_timestamp": "2026-03-24T09:00:00Z",
                "resources": [
                    {"type": "File", "title": "/tmp/a", "exported": True},
                ],
                "edges": [
                    {
                        "relationship": "contains",
                        "source": {"type": "Class", "title": "main"},
                        "target": {"type": "File", "title": "/tmp/a"},
                    }
                ],
            }
        )
        metadata = catalog_metadata(payload)

        for heavy in ("resources", "resources_exported", "edges"):
            self.assertIn(heavy, payload)
            self.assertNotIn(heavy, metadata)
        self.assertEqual(metadata["version"], "4711")
        self.assertEqual(metadata["catalog_uuid"], "uuid1")
        self.assertEqual(metadata["transaction_uuid"], "tx1")
        self.assertEqual(metadata["code_id"], "code1")
        self.assertEqual(metadata["job_id"], "5")
        self.assertEqual(metadata["num_resources"], 1)
        self.assertEqual(metadata["num_resources_exported"], 1)
        self.assertEqual(metadata["hash"], payload["hash"])
        self.assertEqual(metadata["content_hash"], payload["content_hash"])
        self.assertIsInstance(metadata["producer_timestamp"], datetime)


if __name__ == "__main__":
    unittest.main()
