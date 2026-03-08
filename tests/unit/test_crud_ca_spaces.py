import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_spaces import CrudCASpaces

class TestCrudCASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        
        self.crud = CrudCASpaces(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="space1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "space1"})

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=3)
        res = await self.crud.count({"test": 1})
        self.assertEqual(res, 3)
        self.mock_coll.count_documents.assert_called_once_with({"test": 1})
