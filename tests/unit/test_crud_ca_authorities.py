# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime, timezone
from pyppetdb.crud.ca_authorities import CrudCAAuthorities


class TestCrudCAAuthoritiesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_protector = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_crud_secrets = AsyncMock()
        self.mock_crud_secrets.existing_ids = AsyncMock(return_value=set())

        self.crud = CrudCAAuthorities(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector,
            crud_secrets=self.mock_crud_secrets,
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

    async def test_create(self):
        from pyppetdb.model.ca_authorities import CAAuthorityPostInternal

        self.crud._create = AsyncMock(
            return_value={
                "id": "ca1",
                "cn": "CA1",
                "issuer": "CA1",
                "serial_number": "1",
                "not_before": datetime.now(timezone.utc),
                "not_after": datetime.now(timezone.utc),
                "fingerprint": {"sha256": "abc", "sha1": "def", "md5": "ghi"},
                "certificate": "CERT",
                "private_key_encrypted": "ENC",
                "internal": True,
                "chain": [],
                "status": "active",
            }
        )

        payload_dict = {
            "id": "ca1",
            "cn": "CA1",
            "issuer": "CA1",
            "serial_number": "1",
            "not_before": datetime.now(timezone.utc),
            "not_after": datetime.now(timezone.utc),
            "fingerprint": {"sha256": "abc", "sha1": "def", "md5": "ghi"},
            "certificate": "CERT",
            "private_key_encrypted": "ENC",
            "internal": True,
            "chain": [],
            "status": "active",
        }
        payload = CAAuthorityPostInternal(**payload_dict)
        await self.crud.create(_id="ca1", payload=payload, fields=["id"])

        self.crud._create.assert_called_once()
