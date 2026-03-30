import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.nodes_groups import CrudNodesGroups, NodeGroupUpdateInternal


class TestCrudNodesGroupsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        # Mocking CrudNodesGroupsCache to avoid background tasks
        with patch(
            "pyppetdb.crud.nodes_groups.CrudNodesGroupsCache"
        ) as mock_cache_class:
            self.mock_cache = mock_cache_class.return_value
            self.mock_cache.cache = {}
            self.crud = CrudNodesGroups(self.mock_config, self.log, self.mock_coll)

    async def test_create(self):
        self.crud._create = AsyncMock(return_value={"id": "g1"})
        payload = NodeGroupUpdateInternal(id="g1")
        result = await self.crud.create(_id="g1", payload=payload, fields=[])
        self.assertEqual(result.id, "g1")

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="g1")
        self.crud._delete.assert_called_once_with(query={"id": "g1"})

    async def test_delete_node_from_nodes_groups(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.delete_node_from_nodes_groups(node_id="n1")
        self.mock_coll.update_many.assert_called_once()

    async def test_delete_team_from_nodes_groups(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.delete_team_from_nodes_groups(team_id="t1")
        self.mock_coll.update_many.assert_called_once()

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "g1"})
        await self.crud.get(_id="g1", fields=[])
        self.crud._get.assert_called_once()

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=MagicMock())
        await self.crud.resource_exists(_id="g1")
        self.crud._resource_exists.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(_id="g1")
        self.crud._search.assert_called_once()

    async def test_update(self):
        self.crud._update = AsyncMock(return_value={"id": "g1"})
        payload = NodeGroupUpdateInternal(id="g1", teams=["t1"])
        await self.crud.update(_id="g1", payload=payload, fields=[])
        self.crud._update.assert_called_once()

    async def test_reevaluate_node_membership(self):
        from pyppetdb.model.pdb_facts import PuppetDBFacts
        from pyppetdb.model.nodes_groups import (
            NodeGroupGet,
            NodeGroupFilterRule,
            NodeGroupFilterRulePart,
        )

        # Setup mock cache with one group that has a filter
        group1 = NodeGroupGet(
            id="g1",
            filters=[
                NodeGroupFilterRule(
                    part=[NodeGroupFilterRulePart(fact="osfamily", values=["RedHat"])]
                )
            ],
        )
        self.mock_cache.cache = {"doc1": group1}

        facts = PuppetDBFacts(
            certname="node1",
            values={"osfamily": "RedHat"},
            environment="prod",
            producer_timestamp="2026-03-06T00:00:00Z",
            producer="pm1",
        )

        self.mock_coll.bulk_write = AsyncMock()

        matched_groups = await self.crud.reevaluate_node_membership(
            node_id="node1", node_facts=facts
        )

        self.assertEqual(matched_groups, ["g1"])
        self.mock_coll.bulk_write.assert_called_once()

    def test_evaluate_filter_part(self):
        from pyppetdb.model.nodes_groups import NodeGroupFilterRulePart

        part = NodeGroupFilterRulePart(fact="os.family", values=["RedHat", "CentOS"])

        self.assertTrue(
            self.crud._evaluate_filter_part(part, {"os": {"family": "RedHat"}})
        )
        self.assertFalse(
            self.crud._evaluate_filter_part(part, {"os": {"family": "Debian"}})
        )
        self.assertFalse(self.crud._evaluate_filter_part(part, {"other": "val"}))

    def test_compile_filters_from_node_group(self):
        from pyppetdb.model.nodes_groups import (
            NodeGroupGet,
            NodeGroupFilterRule,
            NodeGroupFilterRulePart,
        )

        group = NodeGroupGet(
            filters=[
                NodeGroupFilterRule(
                    part=[NodeGroupFilterRulePart(fact="f1", values=["v1"])]
                )
            ]
        )
        res = self.crud.compile_filters_from_node_group(group)
        self.assertIn("$or", res)


class TestCrudNodesGroupsCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        from pyppetdb.crud.nodes_groups import CrudNodesGroupsCache

        self.cache = CrudNodesGroupsCache(self.log, self.mock_coll)

    async def test_handle_change_insert(self):
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"id": "g1"},
        }
        await self.cache._handle_change(change)
        self.assertIn("doc1", self.cache.cache)
        self.assertEqual(self.cache.cache["doc1"].id, "g1")

    async def test_load_initial_data(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter([{"_id": "d1", "id": "g1"}])
        self.mock_coll.find.return_value = mock_cursor
        await self.cache._load_initial_data()
        self.assertEqual(len(self.cache.cache), 1)
