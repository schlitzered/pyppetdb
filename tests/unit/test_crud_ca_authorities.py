import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from datetime import datetime, timezone
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.model.ca_authorities import CAAuthorityPost

class TestCrudCAAuthoritiesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_protector = MagicMock()
        self.mock_coll = MagicMock()
        
        self.crud = CrudCAAuthorities(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="ca1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "ca1"})

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=5)
        res = await self.crud.count({"some": "query"})
        self.assertEqual(res, 5)
        self.mock_coll.count_documents.assert_called_once_with({"some": "query"})

    async def test_insert(self):
        self.crud._create = AsyncMock(return_value={
            "id": "ca1", "cn": "CA1", "issuer": "CA1", 
            "serial_number": "1", "not_before": datetime.now(timezone.utc), 
            "not_after": datetime.now(timezone.utc),
            "fingerprint": {"sha256": "abc", "sha1": "def", "md5": "ghi"}, "certificate": "CERT",
            "internal": True, "chain": [], "status": "active"
        })
        
        payload = {"id": "ca1", "cn": "CA1"}
        await self.crud.insert(payload=payload, fields=["id"])
        
        self.crud._create.assert_called_once_with(payload=payload, fields=["id"])
