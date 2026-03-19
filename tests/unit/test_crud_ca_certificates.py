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

    async def test_search_multi_spaces(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor
        self.mock_coll.count_documents = AsyncMock(return_value=0)

        await self.crud.search_multi_spaces(space_ids=["s1", "s2"], _id="cert*")

        self.mock_coll.find.assert_called_once()
        args, kwargs = self.mock_coll.find.call_args
        # find is called with filter as first positional or keyword
        query = args[0] if args else kwargs.get("filter")
        self.assertEqual(query["space_id"], {"$in": ["s1", "s2"]})
        self.assertIn("id", query)
