import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_authorities import CrudCAAuthorities

class TestCrudCAAuthoritiesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_protector = MagicMock()
        self.mock_coll = MagicMock()
        
        self.crud = CrudCAAuthorities(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="ca1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "ca1"})

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=5)
        res = await self.crud.count({"some": "query"})
        self.assertEqual(res, 5)
        self.mock_coll.count_documents.assert_called_once_with({"some": "query"})
