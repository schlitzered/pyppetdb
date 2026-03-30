import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache


class TestCrudHieraLookupCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudHieraLookupCache(self.mock_config, self.log, self.mock_coll)

    def test_normalize_facts(self):
        facts = {"os": "linux", "env": "prod"}
        normalized = self.crud._normalize_facts(facts)
        # Should be sorted by key
        self.assertEqual(
            normalized,
            [{"key": "env", "value": "prod"}, {"key": "os", "value": "linux"}],
        )

    async def test_get_cached_not_found(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        result = await self.crud.get_cached(
            key_id="k1", facts={"os": "linux"}, merge=True
        )
        self.assertIsNone(result)

    async def test_get_cached_found(self):
        self.mock_coll.find_one = AsyncMock(
            return_value={"_id": "some_id", "key_id": "k1", "result": {"foo": "bar"}}
        )
        result = await self.crud.get_cached(
            key_id="k1", facts={"os": "linux"}, merge=True
        )
        self.assertEqual(result["result"], {"foo": "bar"})
        self.assertNotIn("_id", result)

    async def test_set_cached(self):
        self.mock_coll.update_one = AsyncMock()
        await self.crud.set_cached(
            key_id="k1", facts={"os": "linux"}, merge=True, result={"foo": "bar"}
        )
        self.mock_coll.update_one.assert_called_once()
        call_args = self.mock_coll.update_one.call_args[1]
        self.assertEqual(call_args["update"]["$set"]["result"], {"foo": "bar"})
        self.assertTrue(call_args["upsert"])

    async def test_delete_by_key_and_facts(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_by_key_and_facts(key_id="k1", facts={"os": "linux"})
        self.mock_coll.delete_many.assert_called_once()
        query = self.mock_coll.delete_many.call_args[1]["filter"]
        self.assertEqual(query["key_id"], "k1")
        self.assertIn("$all", query["facts"])

    async def test_clear_all(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.clear_all()
        self.mock_coll.delete_many.assert_called_once_with(filter={})
