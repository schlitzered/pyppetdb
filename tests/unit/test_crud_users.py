import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.users import CrudUsers, UserPost, UserPut, AuthenticatePost
from pyppetdb.errors import AuthenticationError

class TestCrudUsersUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_crud_ldap = MagicMock()
        self.crud = CrudUsers(self.mock_config, self.log, self.mock_coll, self.mock_crud_ldap)

    async def test_create_internal(self):
        self.crud._create = AsyncMock(return_value={
            "id": "user1",
            "name": "User One",
            "email": "user1@ex.com",
            "backend": "internal"
        })
        payload = UserPost(name="User One", email="user1@ex.com", password="password123")
        result = await self.crud.create(_id="user1", payload=payload, fields=[])
        
        self.assertEqual(result.id, "user1")
        self.crud._create.assert_called_once()
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertEqual(call_args["id"], "user1")
        self.assertEqual(call_args["backend"], "internal")
        self.assertNotEqual(call_args["password"], "password123") # Should be hashed

    async def test_create_external(self):
        self.crud._create = AsyncMock(return_value={
            "id": "user1",
            "name": "User One",
            "email": "user1@ex.com",
            "backend": "ldap"
        })
        payload = UserPut(name="User One", email="user1@ex.com")
        result = await self.crud.create_external(_id="user1", payload=payload, fields=[], backend="ldap")
        
        self.assertEqual(result.id, "user1")
        self.crud._create.assert_called_once()
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertEqual(call_args["backend"], "ldap")

    async def test_check_credentials_internal_success(self):
        from passlib.hash import pbkdf2_sha512
        hashed = pbkdf2_sha512.using(rounds=100000, salt_size=32).hash("password123")
        
        self.mock_coll.find_one = AsyncMock(return_value={
            "id": "user1",
            "password": hashed,
            "backend": "internal"
        })
        
        creds = AuthenticatePost(user="user1", password="password123")
        result = await self.crud.check_credentials(creds)
        self.assertEqual(result, "user1")

    async def test_check_credentials_internal_failure(self):
        from passlib.hash import pbkdf2_sha512
        hashed = pbkdf2_sha512.hash("correct-password")
        
        self.mock_coll.find_one = AsyncMock(return_value={
            "id": "user1",
            "password": hashed,
            "backend": "internal"
        })
        
        creds = AuthenticatePost(user="user1", password="wrong-password")
        with self.assertRaises(AuthenticationError):
            await self.crud.check_credentials(creds)

    async def test_check_credentials_ldap_success(self):
        self.mock_coll.find_one = AsyncMock(return_value={
            "id": "user1",
            "backend": "ldap"
        })
        self.mock_crud_ldap.check_user_credentials = AsyncMock()
        
        creds = AuthenticatePost(user="user1", password="ldap-password")
        result = await self.crud.check_credentials(creds)
        self.assertEqual(result, "user1")
        self.mock_crud_ldap.check_user_credentials.assert_called_once_with(
            user="user1", password="ldap-password"
        )

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="user1")
        self.crud._delete.assert_called_once_with(query={"id": "user1"})

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "user1", "name": "Name"})
        await self.crud.get(_id="user1", fields=[])
        self.crud._get.assert_called_once_with(query={"id": "user1"}, fields=[])

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={"result": [], "meta": {"result_size": 0}})
        await self.crud.search(_id="user1")
        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["id"], {"$regex": "user1"})

    async def test_update_internal_password(self):
        self.crud.get = AsyncMock(return_value=MagicMock(backend="internal"))
        self.crud._update = AsyncMock(return_value={"id": "user1", "name": "New Name"})
        
        payload = UserPut(password="new-password")
        await self.crud.update(_id="user1", payload=payload, fields=[])
        
        call_args = self.crud._update.call_args[1]["payload"]
        self.assertNotEqual(call_args["password"], "new-password")
        self.assertIsNotNone(call_args["password"])

    async def test_update_ldap_password_ignored(self):
        self.crud.get = AsyncMock(return_value=MagicMock(backend="ldap"))
        self.crud._update = AsyncMock(return_value={"id": "user1", "name": "New Name"})
        
        payload = UserPut(password="new-password")
        await self.crud.update(_id="user1", payload=payload, fields=[])
        
        call_args = self.crud._update.call_args[1]["payload"]
        self.assertIsNone(call_args["password"])
