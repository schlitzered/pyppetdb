import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorPost

class TestCrudNodesSecretsRedactorUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_redactor = MagicMock()
        
        # Patch CrudNodesSecretsRedactorCache to avoid background tasks
        with patch("pyppetdb.crud.nodes_secrets_redactor.CrudNodesSecretsRedactorCache") as mock_cache_class:
            self.mock_cache = mock_cache_class.return_value
            self.crud = CrudNodesSecretsRedactor(self.mock_config, self.log, self.mock_coll, self.mock_redactor)

    async def test_create(self):
        self.crud._create = AsyncMock(return_value={"id": "fingerprint"})
        self.mock_redactor.encrypt.return_value = "encrypted"
        
        payload = NodesSecretsRedactorPost(value="secret123")
        result = await self.crud.create(payload=payload)
        
        self.assertEqual(result.id, "fingerprint")
        self.mock_redactor.encrypt.assert_called_once_with("secret123")

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="r1")
        self.crud._delete.assert_called_once_with(query={"id": "r1"})

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={"result": [], "meta": {"result_size": 0}})
        await self.crud.search(_id="r1")
        self.crud._search.assert_called_once()

class TestCrudNodesSecretsRedactorCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_redactor = MagicMock()
        from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactorCache
        self.cache = CrudNodesSecretsRedactorCache(self.log, self.mock_coll, self.mock_redactor)

    async def test_handle_change_insert(self):
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"id": "fingerprint", "value_encrypted": "encrypted"}
        }
        self.mock_redactor.decrypt.return_value = "secret123"
        await self.cache._handle_change(change)
        
        self.mock_redactor.decrypt.assert_called_once_with("encrypted")
        self.mock_redactor.add_secret.assert_called_once_with("secret123")
        self.assertEqual(self.cache._cache["doc1"], "secret123")

    async def test_handle_change_delete(self):
        self.cache._cache["doc1"] = "secret123"
        change = {
            "operationType": "delete",
            "documentKey": {"_id": "doc1"}
        }
        await self.cache._handle_change(change)
        
        self.assertNotIn("doc1", self.cache._cache)
        self.mock_redactor.rebuild.assert_called_once()

    async def test_handle_change_error(self):
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"value_encrypted": "bad"}
        }
        self.mock_redactor.decrypt.side_effect = Exception("fail")
        await self.cache._handle_change(change)
        self.assertNotIn("doc1", self.cache._cache)

    async def test_load_initial_data(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter([
            {"_id": "d1", "value_encrypted": "e1"}
        ])
        self.mock_coll.find.return_value = mock_cursor
        self.mock_redactor.decrypt.return_value = "s1"
        
        await self.cache._load_initial_data()
        self.assertEqual(self.cache._cache["d1"], "s1")
        self.mock_redactor.rebuild.assert_called_with(["s1"])
