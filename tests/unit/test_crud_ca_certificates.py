import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.errors import ResourceNotFound

class TestCrudCACertificatesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_spaces = MagicMock()
        
        self.crud = CrudCACertificates(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            crud_authorities=self.mock_crud_authorities,
            crud_spaces=self.mock_crud_spaces
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        
        await self.crud.delete(space_id="space1", certname="cert1")
        
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "cert1", "space_id": "space1"})

    async def test_delete_not_found(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
        
        with self.assertRaises(ResourceNotFound):
            await self.crud.delete(space_id="space1", certname="cert1")

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=10)
        res = await self.crud.count({"status": "signed"})
        self.assertEqual(res, 10)
        self.mock_coll.count_documents.assert_called_once_with({"status": "signed"})
