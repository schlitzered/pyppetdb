import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_certificates import CrudCACertificates


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

    async def test_revoke_expired(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = [
            {"_id": "obj1", "id": "cert1", "space_id": "s1", "ca_id": "ca1"}
        ]
        self.mock_coll.find.return_value = mock_cursor
        self.mock_coll.update_one = AsyncMock()

        res = await self.crud.revoke_expired()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["space_id"], "s1")
        self.mock_coll.update_one.assert_called_once()

    async def test_lock_acquire_release(self):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        self.mock_coll.update_one = AsyncMock(return_value=mock_result)

        # Lock acquired (modified_count > 0)
        self.assertTrue(await self.crud.lock_acquire())

        # Lock not acquired (modified_count == 0)
        mock_result.modified_count = 0
        self.assertFalse(await self.crud.lock_acquire())

        await self.crud.lock_release()
        self.mock_coll.update_one.assert_called()
