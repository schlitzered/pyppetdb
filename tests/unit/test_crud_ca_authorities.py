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
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

from pyppetdb.crud.ca_authorities import CrudCAAuthoritiesCache
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.watcher import STATE_READY
from pyppetdb.model.ca_authorities import CAAuthorityCacheEntry
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CASigner


def _signer(source):
    return CASigner(
        certificate=MagicMock(spec=x509.Certificate),
        private_key=MagicMock(spec=rsa.RSAPrivateKey),
        source=source,
    )


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


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
            protector=self.mock_protector,
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="ca1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "ca1"})

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

    async def test_search_filters_on_exact_secret_ref(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )

        await self.crud.search(secret_ref="TOK", fields=["id"])

        query = self.crud._search.call_args.kwargs["query"]
        self.assertEqual(query, {"secret_refs": "TOK"})

    async def test_search_without_secret_ref_has_no_filter(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )

        await self.crud.search(fields=["id"])

        self.assertNotIn("secret_refs", self.crud._search.call_args.kwargs["query"])

    def test_secret_refs_index_is_declared(self):
        keys = {
            index.document["name"]: dict(index.document["key"])
            for index in self.crud._indices
        }
        self.assertEqual(keys["idx_secret_refs"], {"secret_refs": 1})

    def test_migrations_in_schema_order(self):
        self.assertEqual(
            [migration.__name__ for migration in self.crud._migrations()],
            ["_add_default_validation_config", "_add_secret_refs"],
        )

    async def test_add_secret_refs_backfills_missing_secret_refs(self):
        config = {
            "san_validation": {
                "http_checks": [
                    {
                        "url": "https://check.example.com",
                        "headers": [{"name": "a", "value": "$secrets[B] $secrets[A]"}],
                    }
                ]
            }
        }
        self.mock_coll.find = MagicMock(
            return_value=_AsyncCursor(
                [{"_id": "o1", "validation_config": config}, {"_id": "o2"}]
            )
        )
        self.mock_coll.update_one = AsyncMock()

        await self.crud._add_secret_refs()

        self.assertEqual(
            self.mock_coll.find.call_args.args[0], {"secret_refs": {"$exists": False}}
        )
        self.mock_coll.update_one.assert_any_await(
            {"_id": "o1"}, {"$set": {"secret_refs": ["A", "B"]}}, session=None
        )
        self.mock_coll.update_one.assert_any_await(
            {"_id": "o2"}, {"$set": {"secret_refs": []}}, session=None
        )

    def _ready(self):
        self.crud.cache.watcher._state = STATE_READY

    def _entry(self, certificate="CERT", private_key=b"KEY", **kwargs):
        return CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca1", certificate=certificate, **kwargs),
            private_key=private_key,
        )

    async def test_get_signer_source_from_ready_cache_skips_backend(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry()
        self.crud._get = AsyncMock()

        result = await self.crud.get_signer_source("ca1")

        self.assertEqual(result, ("CERT", b"KEY"))
        self.crud._get.assert_not_called()

    async def test_get_signer_source_reads_backend_when_not_ready(self):
        self.crud.cache.cache["ca1"] = self._entry(certificate="STALE")
        self.crud._get = AsyncMock(
            return_value={"certificate": "CERT", "private_key_encrypted": "ENC"}
        )
        self.mock_protector.decrypt_string.return_value = "PEMDATA"

        result = await self.crud.get_signer_source("ca1")

        self.assertEqual(result, ("CERT", b"PEMDATA"))
        self.crud._get.assert_awaited_once_with(
            query={"id": "ca1"}, fields=["certificate", "private_key_encrypted"]
        )

    async def test_get_ignores_cache_when_not_ready(self):
        self.crud.cache.cache["ca1"] = self._entry(cn="STALE")
        self.crud._get = AsyncMock(return_value={"id": "ca1", "cn": "FRESH"})

        result = await self.crud.get("ca1", fields=[])

        self.assertEqual(result.cn, "FRESH")

    async def test_cached_get_returns_only_requested_fields(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(
            cn="CACHED",
            crl={
                "crl_pem": "HUGE",
                "generation": 1,
                "updated_at": datetime.now(timezone.utc),
                "next_update": datetime.now(timezone.utc),
            },
        )

        result = await self.crud.get("ca1", fields=["id", "cn"])

        self.assertEqual(result.model_fields_set, {"id", "cn"})
        self.assertEqual(
            result.model_dump(exclude_unset=True), {"id": "ca1", "cn": "CACHED"}
        )

    async def test_cached_get_without_fields_returns_everything(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(cn="CACHED")

        result = await self.crud.get("ca1", fields=[])

        self.assertEqual(result, self.crud.cache.cache["ca1"].authority)

    async def test_cached_get_returns_a_copy(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(cn="CACHED", chain=["A"])

        result = await self.crud.get("ca1", fields=[])
        result.cn = "CHANGED"
        result.chain.append("B")

        cached = self.crud.cache.cache["ca1"].authority
        self.assertEqual(cached.cn, "CACHED")
        self.assertEqual(cached.chain, ["A"])

    async def test_get_uses_cache_when_ready(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(cn="CACHED")
        self.crud._get = AsyncMock()

        result = await self.crud.get("ca1", fields=[])

        self.assertEqual(result.cn, "CACHED")
        self.crud._get.assert_not_called()

    async def test_store_signer_accepts_matching_source(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry()
        signer = _signer(("CERT", b"KEY"))

        self.assertTrue(await self.crud.store_signer("ca1", signer))
        self.assertIs(await self.crud.get_signer("ca1"), signer)

    async def test_store_signer_refuses_stale_source(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(certificate="NEW")
        signer = _signer(("OLD", b"KEY"))

        self.assertFalse(await self.crud.store_signer("ca1", signer))
        self.assertIsNone(await self.crud.get_signer("ca1"))

    async def test_store_signer_refuses_changed_key(self):
        self._ready()
        self.crud.cache.cache["ca1"] = self._entry(private_key=b"NEWKEY")
        signer = _signer(("CERT", b"KEY"))

        self.assertFalse(await self.crud.store_signer("ca1", signer))

    async def test_store_signer_refuses_missing_entry(self):
        self._ready()
        signer = _signer(("CERT", b"KEY"))

        self.assertFalse(await self.crud.store_signer("ca1", signer))
        self.assertNotIn("ca1", self.crud.cache.cache)

    async def test_signer_unavailable_when_not_ready(self):
        self.crud.cache.cache["ca1"] = self._entry()
        signer = _signer(("CERT", b"KEY"))

        self.assertFalse(await self.crud.store_signer("ca1", signer))
        self.crud.cache.cache["ca1"].signer = signer
        self.assertIsNone(await self.crud.get_signer("ca1"))

    def test_authority_get_model_excludes_private_key(self):
        from pyppetdb.model.ca_authorities import (
            CAAuthorityGet,
            CAAuthorityPostInternal,
        )

        self.assertNotIn("private_key_encrypted", CAAuthorityGet.model_fields)
        self.assertIn("private_key_encrypted", CAAuthorityPostInternal.model_fields)

    def test_process_doc_strips_private_key_but_caches_it(self):
        from pyppetdb.crud.ca_authorities import CrudCAAuthoritiesCache

        self.mock_protector.decrypt_string.return_value = "PEMDATA"
        cache = CrudCAAuthoritiesCache(
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector,
        )
        doc = {
            "_id": "objid1",
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

        entry = cache._process_doc(doc)
        obj = entry.authority

        self.assertFalse(hasattr(obj, "private_key_encrypted"))
        self.assertNotIn("private_key_encrypted", obj.model_dump())
        self.assertNotIn("private_key_encrypted", obj.model_dump_json())
        self.assertEqual(entry.private_key, b"PEMDATA")
        self.assertIsNone(entry.signer)
        self.mock_protector.decrypt_string.assert_called_once_with("ENC")

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

    async def test_revoke_only_updates_unrevoked_authorities(self):
        now = datetime.now(timezone.utc)
        self.mock_coll.find_one_and_update = AsyncMock(return_value={"id": "sub"})

        await self.crud.revoke(_id="sub", revocation_date=now)

        kwargs = self.mock_coll.find_one_and_update.call_args.kwargs
        self.assertEqual(kwargs["filter"], {"id": "sub", "status": {"$ne": "revoked"}})
        self.assertEqual(
            kwargs["update"]["$set"], {"status": "revoked", "revocation_date": now}
        )


def _authority_doc(certificate="CERT", private_key="ENC", crl_generation=1):
    now = datetime.now(timezone.utc)
    return {
        "_id": "objid1",
        "id": "ca1",
        "cn": "CA1",
        "issuer": "CA1",
        "serial_number": "1",
        "not_before": now,
        "not_after": now,
        "fingerprint": {"sha256": "abc", "sha1": "def", "md5": "ghi"},
        "certificate": certificate,
        "private_key_encrypted": private_key,
        "internal": True,
        "chain": [],
        "status": "active",
        "crl": {
            "crl_pem": f"CRL{crl_generation}",
            "generation": crl_generation,
            "updated_at": now,
            "next_update": now,
        },
    }


def _change(operation, doc=None):
    change = {"operationType": operation, "documentKey": {"_id": "objid1"}}
    if doc is not None:
        change["fullDocument"] = doc
    return change


class TestCrudCAAuthoritiesCacheSigner(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.protector = MagicMock()
        self.protector.decrypt_string.side_effect = lambda value: f"PEM:{value}"
        self.coll = MagicMock()
        self.cache = CrudCAAuthoritiesCache(
            log=logging.getLogger("test"), coll=self.coll, protector=self.protector
        )
        self.cache.watcher._state = STATE_READY

    async def _with_signer(self, **doc_kwargs):
        await self.cache._handle_change(_change("insert", _authority_doc(**doc_kwargs)))
        signer = _signer(self.cache.cache["ca1"].source)
        self.assertTrue(self.cache.store_signer("ca1", signer))
        return signer

    async def test_crl_only_update_keeps_signer(self):
        signer = await self._with_signer()

        await self.cache._handle_change(
            _change("update", _authority_doc(crl_generation=2))
        )

        self.assertEqual(self.cache.cache["ca1"].authority.crl.generation, 2)
        self.assertIs(self.cache.get_signer("ca1"), signer)

    async def test_certificate_change_drops_signer(self):
        await self._with_signer()

        await self.cache._handle_change(
            _change("replace", _authority_doc(certificate="OTHER"))
        )

        self.assertIsNone(self.cache.get_signer("ca1"))

    async def test_key_change_drops_signer(self):
        await self._with_signer()

        await self.cache._handle_change(
            _change("replace", _authority_doc(private_key="OTHER"))
        )

        self.assertIsNone(self.cache.get_signer("ca1"))

    async def test_delete_drops_signer(self):
        await self._with_signer()

        await self.cache._handle_change(_change("delete"))

        self.assertNotIn("ca1", self.cache.cache)
        self.assertIsNone(self.cache.get_signer("ca1"))

    async def test_resync_keeps_signer_of_unchanged_authority(self):
        signer = await self._with_signer()
        self.coll.find = MagicMock(
            return_value=_AsyncCursor([_authority_doc(crl_generation=3)])
        )

        await self.cache._load()

        self.assertIs(self.cache.get_signer("ca1"), signer)

    async def test_resync_drops_signer_of_changed_authority(self):
        await self._with_signer()
        self.coll.find = MagicMock(
            return_value=_AsyncCursor([_authority_doc(certificate="OTHER")])
        )

        await self.cache._load()

        self.assertIsNone(self.cache.get_signer("ca1"))

    async def test_undecryptable_key_never_stores_signer(self):
        self.protector.decrypt_string.side_effect = ValueError("bad key")
        await self.cache._handle_change(_change("insert", _authority_doc()))
        signer = _signer(("CERT", b""))

        self.assertIsNone(self.cache.cache["ca1"].source)
        self.assertFalse(self.cache.store_signer("ca1", signer))
