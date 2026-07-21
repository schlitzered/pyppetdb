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

    async def test_get_private_key_decrypts(self):
        self.crud._get = AsyncMock(return_value={"private_key_encrypted": "ENC"})
        self.mock_protector.decrypt_string.return_value = "PEMDATA"

        result = await self.crud.get_private_key("ca1")

        self.assertEqual(result, b"PEMDATA")
        self.crud._get.assert_awaited_once_with(
            query={"id": "ca1"}, fields=["private_key_encrypted"]
        )
        self.mock_protector.decrypt_string.assert_called_once_with("ENC")

    async def test_get_private_key_cached_hit_skips_backend(self):
        self.crud.cache.key_cache["ca1"] = b"CACHED"
        self.crud._get = AsyncMock()

        result = await self.crud.get_private_key_cached("ca1")

        self.assertEqual(result, b"CACHED")
        self.crud._get.assert_not_called()

    async def test_get_private_key_cached_miss_reads_backend(self):
        self.crud._get = AsyncMock(return_value={"private_key_encrypted": "ENC"})
        self.mock_protector.decrypt_string.return_value = "PEMDATA"

        result = await self.crud.get_private_key_cached("ca1")

        self.assertEqual(result, b"PEMDATA")
        self.crud._get.assert_awaited_once()

    async def test_sync_crl_data_success(self):
        now = datetime.now(timezone.utc)
        self.mock_coll.find_one = AsyncMock(
            side_effect=[
                {"crl": {"generation": 5}},
                {
                    "crl": {
                        "crl_pem": "PEM",
                        "generation": 6,
                        "updated_at": now,
                        "next_update": now,
                    }
                },
            ]
        )
        self.mock_coll.update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )

        result = await self.crud.sync_crl_data(
            ca_id="ca1", crl_pem="PEM", next_update=now
        )

        self.assertEqual(result.generation, 6)
        filter_arg, update_arg = self.mock_coll.update_one.call_args[0]
        self.assertEqual(filter_arg, {"id": "ca1", "crl.generation": 5})
        self.assertEqual(update_arg["$set"]["crl.generation"], 6)
        self.assertEqual(update_arg["$set"]["crl.crl_pem"], "PEM")

    async def test_sync_crl_data_ca_not_found(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        with self.assertRaises(Exception):
            await self.crud.sync_crl_data(
                ca_id="ca1", crl_pem="PEM", next_update=datetime.now(timezone.utc)
            )

    async def test_sync_crl_data_without_crl_raises(self):
        self.mock_coll.find_one = AsyncMock(return_value={"id": "ca1"})
        with self.assertRaises(Exception):
            await self.crud.sync_crl_data(
                ca_id="ca1", crl_pem="PEM", next_update=datetime.now(timezone.utc)
            )

    async def test_sync_crl_data_retries_on_generation_conflict(self):
        now = datetime.now(timezone.utc)
        self.mock_coll.find_one = AsyncMock(
            side_effect=[
                {"crl": {"generation": 5}},
                {"crl": {"generation": 6}},
                {
                    "crl": {
                        "crl_pem": "PEM",
                        "generation": 7,
                        "updated_at": now,
                        "next_update": now,
                    }
                },
            ]
        )
        self.mock_coll.update_one = AsyncMock(
            side_effect=[
                MagicMock(modified_count=0),
                MagicMock(modified_count=1),
            ]
        )

        result = await self.crud.sync_crl_data(
            ca_id="ca1", crl_pem="PEM", next_update=now
        )

        self.assertEqual(result.generation, 7)
        self.assertEqual(self.mock_coll.update_one.await_count, 2)
