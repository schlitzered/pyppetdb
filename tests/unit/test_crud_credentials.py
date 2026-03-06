import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from datetime import datetime, UTC
from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.model.credentials import CredentialPost, CredentialPut
from pyppetdb.errors import CredentialError

class TestCrudCredentialsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudCredentials(self.mock_config, self.log, self.mock_coll)

    async def test_create_credential(self):
        with patch.object(CrudCredentials, "_ph") as mock_ph:
            mock_ph.hash.return_value = "hashed_secret"
            self.crud._create = AsyncMock(return_value={"id": "cred-id"})
            
            payload = CredentialPost(description="test cred")
            result = await self.crud.create(owner="owner1", payload=payload)
            
            self.assertEqual(result.description, "test cred")
            self.crud._create.assert_called_once()
            mock_ph.hash.assert_called_once()

    async def test_check_credential_success(self):
        with patch.object(CrudCredentials, "_ph") as mock_ph:
            mock_ph.verify.return_value = True
            self.crud._get = AsyncMock(return_value={"secret": "hashed_secret", "owner": "owner1"})
            
            mock_request = MagicMock()
            mock_request.headers = {"x-secret": "clear_secret", "x-secret-id": "cred-id"}
            
            owner = await self.crud.check_credential(mock_request)
            self.assertEqual(owner, "owner1")
            mock_ph.verify.assert_called_once_with("hashed_secret", "clear_secret")

    async def test_check_credential_failure(self):
        with patch.object(CrudCredentials, "_ph") as mock_ph:
            from argon2.exceptions import VerifyMismatchError
            mock_ph.verify.side_effect = VerifyMismatchError
            self.crud._get = AsyncMock(return_value={"secret": "hashed_secret", "owner": "owner1"})
            
            mock_request = MagicMock()
            mock_request.headers = {"x-secret": "wrong_secret", "x-secret-id": "cred-id"}
            
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
