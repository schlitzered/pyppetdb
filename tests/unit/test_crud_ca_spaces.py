import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpacePut


class TestCrudCASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()

        self.crud = CrudCASpaces(
            config=self.mock_config, log=self.log, coll=self.mock_coll
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(query={"id": "space1"})
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "space1"})

    async def test_insert(self):
        self.crud._create = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca1", "ca_id_history": []}
        )
        payload = {"id": "space1", "ca_id": "ca1", "ca_id_history": []}
        await self.crud.insert(payload=payload, fields=["id"])

        self.crud._create.assert_called_once_with(payload=payload, fields=["id"])

    async def test_update(self):
        self.crud._update = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca2", "ca_id_history": ["ca1"]}
        )

        payload = {"ca_id": "ca2", "ca_id_history": ["ca1"]}
        await self.crud.update(query={"id": "space1"}, payload=payload, fields=["id"])

        self.crud._update.assert_called_once_with(
            query={"id": "space1"}, payload=payload, fields=["id"], upsert=False
        )

    async def test_search_by_ca(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "s1"}])
        self.mock_coll.find.return_value = mock_cursor

        res = await self.crud.search_by_ca("ca1")
        self.assertEqual(len(res), 1)
        self.mock_coll.find.assert_called_once()
        args = self.mock_coll.find.call_args[0][0]
        self.assertIn("$or", args)
