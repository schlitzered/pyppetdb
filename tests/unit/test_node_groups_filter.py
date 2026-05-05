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
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.model.nodes_groups import (
    NodeGroupGet,
    NodeGroupFilterRule,
    NodeGroupFilterRulePart,
)


class TestNodeGroupsFilterUnit(unittest.TestCase):
    def test_compile_filters(self):
        # 1. Test empty filters
        ng = NodeGroupGet(id="test", filters=[])
        self.assertEqual(
            CrudNodesGroups.compile_filters_from_node_group(ng), {"id": None}
        )

        # 2. Test single filter with single part
        ng = NodeGroupGet(
            id="test",
            filters=[
                NodeGroupFilterRule(
                    part=[NodeGroupFilterRulePart(fact="role", values=["web"])]
                )
            ],
        )
        expected = {"$or": [{"$and": [{"facts.role": {"$in": ["web"]}}]}]}
        self.assertEqual(CrudNodesGroups.compile_filters_from_node_group(ng), expected)

        # 3. Test multiple parts (AND) and multiple rules (OR)
        ng = NodeGroupGet(
            id="test",
            filters=[
                NodeGroupFilterRule(
                    part=[
                        NodeGroupFilterRulePart(fact="role", values=["web"]),
                        NodeGroupFilterRulePart(fact="env", values=["prod"]),
                    ]
                ),
                NodeGroupFilterRule(
                    part=[NodeGroupFilterRulePart(fact="os", values=["Linux"])]
                ),
            ],
        )
        expected = {
            "$or": [
                {
                    "$and": [
                        {"facts.role": {"$in": ["web"]}},
                        {"facts.env": {"$in": ["prod"]}},
                    ]
                },
                {"$and": [{"facts.os": {"$in": ["Linux"]}}]},
            ]
        }
        self.assertEqual(CrudNodesGroups.compile_filters_from_node_group(ng), expected)

    def test_evaluate_filter_part(self):
        # Mocking the part
        part = NodeGroupFilterRulePart(fact="os.name", values=["Debian", "Ubuntu"])

        # Match
        self.assertTrue(
            CrudNodesGroups._evaluate_filter_part(part, {"os": {"name": "Debian"}})
        )
        self.assertTrue(
            CrudNodesGroups._evaluate_filter_part(part, {"os": {"name": "Ubuntu"}})
        )

        # No match
        self.assertFalse(
            CrudNodesGroups._evaluate_filter_part(part, {"os": {"name": "CentOS"}})
        )
        self.assertFalse(
            CrudNodesGroups._evaluate_filter_part(part, {"os": {"other": "Debian"}})
        )
        self.assertFalse(
            CrudNodesGroups._evaluate_filter_part(part, {"other": "value"})
        )

        # Test flat fact
        part_flat = NodeGroupFilterRulePart(fact="env", values=["prod"])
        self.assertTrue(
            CrudNodesGroups._evaluate_filter_part(part_flat, {"env": "prod"})
        )
        self.assertFalse(
            CrudNodesGroups._evaluate_filter_part(part_flat, {"env": "dev"})
        )
