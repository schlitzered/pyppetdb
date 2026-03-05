import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.model.teams import TeamPost, TeamPut

class TestCrudTeamsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudTeams(self.mock_config, self.log, self.mock_coll)

    async def test_create(self):
        self.crud._create = AsyncMock(return_value={
            "id": "team1",
            "ldap_group": "group1",
            "users": ["user1"]
        })
        payload = TeamPost(ldap_group="group1", users=["user1"])
        result = await self.crud.create(_id="team1", payload=payload, fields=[])
        
        self.assertEqual(result.id, "team1")
        self.crud._create.assert_called_once()
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertEqual(call_args["id"], "team1")

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="team1")
        self.crud._delete.assert_called_once_with(query={"id": "team1"})

    async def test_delete_user_from_teams(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.delete_user_from_teams(user_id="user1")
        self.mock_coll.update_many.assert_called_once()
        call_args = self.mock_coll.update_many.call_args[1]
        self.assertEqual(call_args["update"]["$pull"]["users"], "user1")

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={
            "id": "team1",
            "ldap_group": "group1",
            "users": []
        })
        await self.crud.get(_id="team1", fields=[])
        self.crud._get.assert_called_once_with(query={"id": "team1"}, fields=[])

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=True)
        exists = await self.crud.resource_exists(_id="team1")
        self.assertTrue(exists)
        self.crud._resource_exists.assert_called_once_with(query={"id": "team1"})

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={"result": [], "meta": {"result_size": 0}})
        await self.crud.search(_id="team1", ldap_group="group1", users="user1")
        
        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["id"], {"$regex": "team1"})
        self.assertEqual(call_args["query"]["ldap_group"], {"$regex": "group1"})
        self.assertEqual(call_args["query"]["users"], {"$regex": "user1"})

    async def test_update(self):
        self.crud._update = AsyncMock(return_value={
            "id": "team1",
            "ldap_group": "new_group",
            "users": ["user2"]
        })
        payload = TeamPut(ldap_group="new_group", users=["user2"])
        await self.crud.update(_id="team1", payload=payload, fields=[])
        self.crud._update.assert_called_once_with(
            query={"id": "team1"}, fields=[], payload={"ldap_group": "new_group", "users": ["user2"]}
        )
