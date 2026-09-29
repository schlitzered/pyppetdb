# Copyright 2024 Stephan Schultchen
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

import logging
import unittest
from unittest.mock import MagicMock

from pyppetdb.crud.nodes_resources import CrudNodesResources


class TestCrudNodesResourcesIndexes(unittest.TestCase):
    def test_lookup_indexes_end_in_node_id_so_subqueries_distinct_scan(self):
        crud = CrudNodesResources(MagicMock(), logging.getLogger("test"), MagicMock())
        keys = {
            index.document["name"]: list(index.document["key"].items())
            for index in crud._indices
        }
        self.assertEqual(
            keys["idx_node_id"], [("node_id", 1), ("type", 1), ("title", 1), ("disabled", 1)]
        )
        self.assertEqual(keys["idx_type"], [("type", 1), ("node_id", 1)])
        self.assertEqual(
            keys["idx_type_title"], [("type", 1), ("title", 1), ("node_id", 1)]
        )

    def test_exported_resources_have_small_partial_indexes(self):
        crud = CrudNodesResources(MagicMock(), logging.getLogger("test"), MagicMock())
        indexes = {index.document["name"]: index.document for index in crud._indices}
        for name, leading in (("idx_exported_type", "type"), ("idx_exported_node_id", "node_id")):
            self.assertEqual(indexes[name]["partialFilterExpression"], {"exported": True})
            self.assertEqual(next(iter(indexes[name]["key"])), leading)
