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

        self.crud = CrudCACertificates(
            config=self.mock_config, log=self.log, coll=self.mock_coll
        )

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=10)
        res = await self.crud.count({"status": "signed"})
        self.assertEqual(res, 10)
        self.mock_coll.count_documents.assert_called_once_with({"status": "signed"})
