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
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="space1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "space1"})

    async def test_create(self):
        self.crud._create = AsyncMock(return_value={"id": "space1", "authority_id": "ca1", "authority_id_history": []})
        payload = CASpacePost(ca_id="ca1")
        await self.crud.create(_id="space1", payload=payload)
        
        args = self.crud._create.call_args[1]
        self.assertEqual(args["payload"]["id"], "space1")
        self.assertEqual(args["payload"]["authority_id"], "ca1")
        self.assertEqual(args["payload"]["authority_id_history"], [])

    async def test_update_authority(self):
        # Setup mock for get()
        self.mock_coll.find_one = AsyncMock(side_effect=[
            {"id": "space1", "authority_id": "ca1", "authority_id_history": []}, # first call inside update
            {"id": "space1", "authority_id": "ca2", "authority_id_history": ["ca1"]} # final get()
        ])
        self.mock_coll.update_one = AsyncMock()
        
        payload = CASpacePut(authority_id="ca2")
        await self.crud.update("space1", payload)
        
        self.mock_coll.update_one.assert_called_once()
        args, kwargs = self.mock_coll.update_one.call_args
        self.assertEqual(args[0], {"id": "space1"})
        self.assertEqual(args[1]["$set"], {"authority_id": "ca2"})
        self.assertEqual(args[1]["$push"], {"authority_id_history": "ca1"})

    async def test_search_by_ca(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "s1"}])
        self.mock_coll.find.return_value = mock_cursor
        
        res = await self.crud.search_by_ca("ca1")
        self.assertEqual(len(res), 1)
        self.mock_coll.find.assert_called_once()
        args = self.mock_coll.find.call_args[0][0]
        self.assertIn("$or", args)
