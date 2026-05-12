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

import datetime
import logging
import asyncio
import typing
from typing import List, Optional
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorClientSession

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.model.ca_authorities import CAAuthorityGet, CAAuthorityPost
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CACRL
from pyppetdb.model.ca_authorities import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.ca.validation_protector import CAValidationProtector
from pyppetdb.model.ca_validation import CAValidationConfig


class CrudCAAuthoritiesCache:
    def __init__(self, log: logging.Logger, coll: AsyncIOMotorCollection):
        self._coll = coll
        self._log = log
        self._cache = {}
        self._doc_to_id = {}
        self._initialized = False

    @property
    def cache(self) -> dict["str", CAAuthorityGet]:
        return self._cache

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    async def run(self):
        if self._initialized:
            return
        await self._load_initial_data()
        asyncio.create_task(self._watch_changes())
        self._initialized = True

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({})
            async for doc in cursor:
                self._cache[doc["id"]] = CAAuthorityGet(**doc)
                self._doc_to_id[doc["_id"]] = doc["id"]
            self.log.info(
                f"Loaded {len(self._cache)} initial CA authorities into cache"
            )
        except Exception as e:
            self.log.error(f"Failed to load initial CA authorities: {e}")

    async def _watch_changes(self):
        try:
            async with self.coll.watch(full_document="updateLookup") as change_stream:
                self.log.info("Change stream watcher started for CA authorities")
                async for change in change_stream:
                    operation = change["operationType"]
                    doc_id = change["documentKey"]["_id"]
                    if operation in ("insert", "replace", "update"):
                        doc = change.get("fullDocument")
                        if doc:
                            self._cache[doc["id"]] = CAAuthorityGet(**doc)
                            self._doc_to_id[doc_id] = doc["id"]
                    elif operation == "delete":
                        custom_id = self._doc_to_id.pop(doc_id, None)
                        if custom_id:
                            self._cache.pop(custom_id, None)
                            self.log.info(
                                f"Removed CA authority {custom_id} from cache"
                            )
                        else:
                            await self._load_initial_data()

        except Exception as e:
            self.log.error(f"Error in CA authorities change stream: {e}")
            await asyncio.sleep(5)
            asyncio.create_task(self._watch_changes())


class CrudCAAuthorities(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        super().__init__(config, log, coll, schema_model=CAAuthorityPost)
        self._protector = protector
        self._cache = CrudCAAuthoritiesCache(log=log, coll=coll)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    @property
    def cache(self):
        return self._cache

    async def get_cached(self, _id: str) -> CAAuthorityGet:
        if _id not in self.cache.cache:
            # Fallback to DB if not in cache (maybe not yet initialized or just inserted)
            return await self.get(_id, fields=None)
        return self.cache.cache[_id]

    @property
    def protector(self):
        return self._protector

    def _has_masks(self, config: CAValidationConfig) -> bool:
        if (
            not config
            or not config.san_validation
            or not config.san_validation.http_checks
        ):
            return False
        for check in config.san_validation.http_checks:
            if check.username == "*****" or check.password == "*****":
                return True
            if check.headers:
                if any(h.value == "*****" for h in check.headers):
                    return True
        return False

    async def _encrypt_validation_config(
        self, payload: dict, ca_id: Optional[str] = None
    ):
        if "validation_config" in payload and payload["validation_config"]:
            protector = CAValidationProtector(self._protector)
            config = CAValidationConfig(**payload["validation_config"])

            if self._has_masks(config) and ca_id:
                try:
                    current = await self.get(ca_id, fields=["validation_config"])
                    if current.validation_config:
                        config = protector.merge_secrets(
                            config, current.validation_config
                        )
                except Exception:
                    pass

            encrypted = protector.encrypt_config(config)
            payload["validation_config"] = encrypted.model_dump()

    async def _create_index(self) -> None:
        await super()._create_index()
        await self.cache.run()

    async def migrate_1(
        self, session: Optional[AsyncIOMotorClientSession] = None
    ) -> None:
        await super().migrate_1(session=session)
        from pyppetdb.model.ca_validation import CAValidationConfig

        default_config = CAValidationConfig().model_dump()
        res = await self.coll.update_many(
            {"validation_config": {"$exists": False}},
            {"$set": {"validation_config": default_config}},
            session=session,
        )
        if res.modified_count > 0:
            self.log.info(
                f"Migrated {res.modified_count} CA Authorities with default validation config"
            )

    async def insert(self, payload: dict, fields: list) -> CAAuthorityGet:
        await self._encrypt_validation_config(payload, ca_id=payload.get("id"))
        result = await self._create(payload=payload, fields=fields)
        return CAAuthorityGet(**result)

    async def update(
        self, query: dict, payload: dict, fields: list, upsert: bool = False
    ) -> CAAuthorityGet:
        await self._encrypt_validation_config(payload, ca_id=query.get("id"))
        result = await self._update(
            query=query, payload=payload, fields=fields, upsert=upsert
        )
        return CAAuthorityGet(**result)

    async def get(self, _id: str, fields: list) -> CAAuthorityGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CAAuthorityGet(**result)

    async def resource_exists(self, _id: str) -> str:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def delete(self, _id: str) -> None:
        await self._delete(query={"id": _id})

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_private_key(self, _id: str) -> bytes:
        result = await self._get(query={"id": _id}, fields=["private_key_encrypted"])
        decrypted = self._protector.decrypt_string(result["private_key_encrypted"])
        return decrypted.encode()

    async def get_revoked(self, parent_id: str) -> list[dict]:
        cursor = self.coll.find(
            {"parent_id": parent_id, "status": "revoked"},
            {"serial_number": 1, "revocation_date": 1},
        )
        revoked = []
        async for ca in cursor:
            revoked.append(
                {
                    "serial_number": int(ca["serial_number"]),
                    "revocation_date": ca["revocation_date"],
                }
            )
        return revoked

    async def search(
        self,
        _id: typing.Optional[str] = None,
        parent_id: typing.Optional[str] = None,
        cn: typing.Optional[str] = None,
        fingerprint: typing.Optional[str] = None,
        internal: typing.Optional[bool] = None,
        status: typing.Optional[CAStatus] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CAAuthorityGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "parent_id", parent_id)
        self._filter_re(query, "cn", cn)
        self._filter_re(query, "fingerprint.sha256", fingerprint)
        if internal is not None:
            query["internal"] = internal
        if status:
            query["status"] = status

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CAAuthorityGetMulti(**result)

    async def sync_crl_data(
        self,
        ca_id: str,
        crl_pem: str,
        next_update: datetime.datetime,
    ) -> CACRL:
        while True:
            ca_doc = await self.coll.find_one({"id": ca_id}, {"crl": 1})
            if not ca_doc:
                raise Exception(f"CA {ca_id} not found")
            if "crl" not in ca_doc:
                raise Exception(f"CA {ca_id} has no CRL (external CA?)")

            current_generation = ca_doc["crl"]["generation"]
            now = datetime.datetime.now(datetime.timezone.utc)

            result = await self.coll.update_one(
                {"id": ca_id, "crl.generation": current_generation},
                {
                    "$set": {
                        "crl.crl_pem": crl_pem,
                        "crl.updated_at": now,
                        "crl.next_update": next_update,
                        "crl.locked_at": None,
                        "crl.generation": current_generation + 1,
                    }
                },
            )
            if result.modified_count > 0:
                updated = await self.coll.find_one({"id": ca_id}, {"crl": 1})
                return CACRL(**updated["crl"])

    async def lock_crl_acquire(
        self,
        ca_id: str,
        lock_timeout_minutes: int = 10,
    ) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        timeout = now - datetime.timedelta(minutes=lock_timeout_minutes)

        result = await self.coll.update_one(
            {
                "id": ca_id,
                "$or": [
                    {"crl.locked_at": None},
                    {"crl.locked_at": {"$lt": timeout}},
                ],
            },
            {"$set": {"crl.locked_at": now}},
        )
        return result.modified_count > 0

    async def lock_crl_release(self, ca_id: str) -> None:
        await self.coll.update_one({"id": ca_id}, {"$set": {"crl.locked_at": None}})

    async def find_expiring_crls(self, threshold_hours: int = 4) -> List[str]:
        threshold = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=threshold_hours
        )
        cursor = self.coll.find({"crl.next_update": {"$lt": threshold}}, {"id": 1})
        return [doc["id"] async for doc in cursor]
