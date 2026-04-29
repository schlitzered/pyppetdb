import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.model.hiera_level_data import HieraLevelDataPost, HieraLevelDataPut
from pyppetdb.errors import QueryParamValidationError


class TestCrudHieraLevelDataUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudHieraLevelData(self.log, self.mock_config, self.mock_coll)

    def test_normalize_facts(self):
        level_id = "nodes/{certname}"
        facts = {"certname": "node1.example.com", "os": "linux", "env": "prod"}
        normalized = self.crud._normalize_facts(level_id, facts)
        self.assertEqual(normalized, {"certname": "node1.example.com"})

        level_id = "env/{environment}/os/{osfamily}"
        facts = {"environment": "prod", "osfamily": "RedHat", "foo": "bar"}
        normalized = self.crud._normalize_facts(level_id, facts)
        self.assertEqual(normalized, {"environment": "prod", "osfamily": "RedHat"})

        # Nested fact
        level_id = "role/{pyppetdb.role}"
        facts = {"pyppetdb.role": "web", "other": "ignored"}
        normalized = self.crud._normalize_facts(level_id, facts)
        self.assertEqual(normalized, {"pyppetdb.role": "web"})

    def test_validate_level_and_id_success(self):
        level_id = "nodes/{certname}"
        data_id = "nodes/node1.example.com"
        facts = {"certname": "node1.example.com"}
        # Should not raise
        self.crud._validate_level_and_id(level_id, data_id, facts)

    def test_validate_level_and_id_success_nested(self):
        level_id = "role/{pyppetdb.role}"
        data_id = "role/web"
        facts = {"pyppetdb.role": "web"}
        # Should not raise
        self.crud._validate_level_and_id(level_id, data_id, facts)

    def test_validate_level_and_id_failure_mismatch(self):
        level_id = "nodes/{certname}"
        data_id = "nodes/wrong.example.com"
        facts = {"certname": "node1.example.com"}
        with self.assertRaises(QueryParamValidationError) as cm:
            self.crud._validate_level_and_id(level_id, data_id, facts)
        self.assertIn("not matching expanded level_id", str(cm.exception))

    def test_validate_level_and_id_failure_missing_fact(self):
        level_id = "nodes/{certname}"
        data_id = "nodes/node1.example.com"
        facts = {"os": "linux"}
        with self.assertRaises(QueryParamValidationError) as cm:
            self.crud._validate_level_and_id(level_id, data_id, facts)
        self.assertIn("missing fact", str(cm.exception))

    async def test_create(self):
        self.crud._create = AsyncMock(
            return_value={
                "id": "nodes/node1.example.com",
                "key_id": "ssh_keys",
                "level_id": "nodes/{certname}",
                "data": {"key": "abc"},
                "facts": {"certname": "node1.example.com"},
                "priority": 10,
            }
        )

        payload = HieraLevelDataPost(
            data={"key": "abc"},
            facts={"certname": "node1.example.com", "other": "ignored"},
        )

        result = await self.crud.create(
            _id="nodes/node1.example.com",
            key_id="ssh_keys",
            level_id="nodes/{certname}",
            payload=payload,
            priority=10,
            fields=[],
        )

        self.assertEqual(result.id, "nodes/node1.example.com")
        self.assertEqual(result.facts, {"certname": "node1.example.com"})
        self.crud._create.assert_called_once()

        # Verify normalization happened before _create
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertEqual(call_args["facts"], {"certname": "node1.example.com"})

    async def test_create_validation_failure(self):
        payload = HieraLevelDataPost(
            data={"key": "abc"}, facts={"certname": "wrong.example.com"}
        )
        with self.assertRaises(QueryParamValidationError):
            await self.crud.create(
                _id="nodes/node1.example.com",
                key_id="ssh_keys",
                level_id="nodes/{certname}",
                payload=payload,
                priority=10,
                fields=[],
            )

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="d1", key_id="k1", level_id="l1")
        self.crud._delete.assert_called_once_with(
            query={
                "id": "d1",
                "key_id": "k1",
                "level_id": "l1",
            }
        )

    async def test_delete_all_from_level(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_all_from_level(level_id="l1")
        self.mock_coll.delete_many.assert_called_once_with(filter={"level_id": "l1"})

    async def test_update_priority_by_level(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.update_priority_by_level(level_id="l1", priority=20)
        self.mock_coll.update_many.assert_called_once_with(
            filter={"level_id": "l1"}, update={"$set": {"priority": 20}}
        )

    async def test_delete_all_from_key(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_all_from_key(key_id="k1")
        self.mock_coll.delete_many.assert_called_once_with(filter={"key_id": "k1"})

    async def test_get(self):
        self.crud._get = AsyncMock(
            return_value={
                "id": "d1",
                "key_id": "k1",
                "level_id": "l1",
                "data": {},
                "facts": {},
            }
        )
        await self.crud.get(_id="d1", key_id="k1", level_id="l1", fields=[])
        self.crud._get.assert_called_once_with(
            query={"id": "d1", "key_id": "k1", "level_id": "l1"}, fields=[]
        )

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=True)
        exists = await self.crud.resource_exists(_id="d1", key_id="k1", level_id="l1")
        self.assertTrue(exists)
        self.crud._resource_exists.assert_called_once_with(
            query={"id": "d1", "key_id": "k1", "level_id": "l1"}
        )

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(level_id="l1", key_id="k1")

        # Check if _filter_re was called (indirectly via query building)
        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["level_id"], {"$regex": "l1"})
        self.assertEqual(call_args["query"]["key_id"], {"$regex": "k1"})

    async def test_update(self):
        self.crud._update = AsyncMock(
            return_value={
                "id": "d1",
                "key_id": "k1",
                "level_id": "l1",
                "data": {"new": "val"},
                "facts": {},
            }
        )
        payload = HieraLevelDataPut(data={"new": "val"})
        await self.crud.update(
            _id="d1", key_id="k1", level_id="l1", payload=payload, fields=[]
        )

        self.crud._update.assert_called_once_with(
            query={"id": "d1", "key_id": "k1", "level_id": "l1"},
            fields=[],
            payload={"data": {"new": "val"}},
            upsert=False,
        )
