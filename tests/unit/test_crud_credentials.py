import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from datetime import datetime, UTC
from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.model.credentials import CredentialPost, CredentialPut
from pyppetdb.errors import CredentialError
from passlib.hash import pbkdf2_sha512

class TestCrudCredentialsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudCredentials(self.mock_config, self.log, self.mock_coll)

    async def test_create_credential(self):
        # Mocking self._create (inherited from CrudMongo)
        self.crud._create = AsyncMock(return_value={"id": "some-uuid"})
        
        payload = CredentialPost(description="Test description")
        result = await self.crud.create(owner="test-owner", payload=payload)
        
        self.assertEqual(result.description, "Test description")
        self.assertTrue(len(result.secret) > 0)
        self.crud._create.assert_called_once()
        
        # Verify secret hashing
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertTrue(pbkdf2_sha512.verify(result.secret, call_args["secret"]))
        self.assertEqual(call_args["owner"], "test-owner")

    async def test_check_credential_success(self):
        # Mocking self._get (inherited from CrudMongo)
        clear_secret = "my-super-secret"
        hashed_secret = pbkdf2_sha512.hash(clear_secret)
        
        self.crud._get = AsyncMock(return_value={
            "secret": hashed_secret,
            "owner": "test-owner"
        })
        
        mock_request = MagicMock()
        mock_request.headers = {
            "x-secret": clear_secret,
            "x-secret-id": "cred-id"
        }
        
        owner = await self.crud.check_credential(mock_request)
        self.assertEqual(owner, "test-owner")
        self.crud._get.assert_called_once_with(query={"id": "cred-id"}, fields=["secret", "owner"])

    async def test_check_credential_failure_wrong_secret(self):
        hashed_secret = pbkdf2_sha512.hash("correct-secret")
        self.crud._get = AsyncMock(return_value={
            "secret": hashed_secret,
            "owner": "test-owner"
        })
        
        mock_request = MagicMock()
        mock_request.headers = {
            "x-secret": "wrong-secret",
            "x-secret-id": "cred-id"
        }
        
        with self.assertRaises(CredentialError):
            await self.crud.check_credential(mock_request)

    async def test_check_credential_failure_missing_headers(self):
        mock_request = MagicMock()
        mock_request.headers = {}
        
        with self.assertRaises(CredentialError):
            await self.crud.check_credential(mock_request)

    async def test_delete_credential(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="cred-id", owner="owner1")
        self.crud._delete.assert_called_once_with(query={"id": "cred-id", "owner": "owner1"})

    async def test_delete_all_from_owner(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete_all_from_owner(owner="owner1")
        self.crud._delete.assert_called_once_with(query={"owner": "owner1"})

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={
            "id": "cred-id",
            "owner": "owner1",
            "created": datetime(2026, 3, 6, tzinfo=UTC)
        })
        result = await self.crud.get(_id="cred-id", owner="owner1", fields=[])
        self.assertEqual(result.id, "cred-id")
        self.crud._get.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={
            "result": [{"id": "c1", "created": datetime(2026, 3, 6, tzinfo=UTC)}],
            "meta": {"result_size": 1}
        })
        result = await self.crud.search(owner="owner1")
        self.assertEqual(len(result.result), 1)
        self.crud._search.assert_called_once_with(
            query={"owner": "owner1"}, fields=None, sort=None, sort_order=None, page=None, limit=None
        )

    async def test_update(self):
        self.crud._update = AsyncMock(return_value={
            "id": "c1",
            "owner": "o1",
            "created": datetime(2026, 3, 6, tzinfo=UTC)
        })
        payload = CredentialPut(description="new desc")
        await self.crud.update(_id="c1", owner="o1", payload=payload, fields=[])
        self.crud._update.assert_called_once_with(
            query={"id": "c1", "owner": "o1"}, fields=[], payload={"description": "new desc"}
        )
