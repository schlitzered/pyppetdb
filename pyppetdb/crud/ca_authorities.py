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
from typing import Optional
import pymongo
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorClientSession

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.model.ca_authorities import (
    CAAuthorityGet,
    CAAuthorityPostInternal,
)
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CAAuthorityPutInternal
from pyppetdb.model.ca_authorities import CACRL
from pyppetdb.model.ca_authorities import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import DataDelete
from pyppetdb.ca.config_validation import validate_secret_references
from pyppetdb.ca.secret_resolver import extract_references
from pyppetdb.crud.ca_secrets import CrudCASecrets
from pyppetdb.model.ca_validation import CAValidationConfig


class CrudCAAuthoritiesCache:
    def __init__(
        self,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        self._coll = coll
        self._log = log
        self._protector = protector
        self._cache = {}
        self._key_cache = {}
        self._doc_to_id = {}
        self._initialized = False

    @property
    def cache(self) -> dict["str", CAAuthorityGet]:
        return self._cache

    @property
    def key_cache(self) -> dict["str", bytes]:
        return self._key_cache

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

    def _process_doc(self, doc: dict) -> CAAuthorityGet:
        obj = CAAuthorityGet(**doc)
        if doc.get("private_key_encrypted"):
            try:
                decrypted = self._protector.decrypt_string(doc["private_key_encrypted"])
                self._key_cache[obj.id] = decrypted.encode()
            except Exception as e:
                self.log.error(f"Failed to decrypt private key for CA {obj.id}: {e}")
        return obj

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({})
            async for doc in cursor:
                obj = self._process_doc(doc)
                self._cache[obj.id] = obj
                self._doc_to_id[doc["_id"]] = obj.id
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
                            obj = self._process_doc(doc)
                            self._cache[obj.id] = obj
                            self._doc_to_id[doc_id] = obj.id
                    elif operation == "delete":
                        custom_id = self._doc_to_id.pop(doc_id, None)
                        if custom_id:
                            self._cache.pop(custom_id, None)
                            self._key_cache.pop(custom_id, None)
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
        crud_secrets: CrudCASecrets,
    ):
        super().__init__(config, log, coll, schema_model=CAAuthorityGet)
        self._protector = protector
        self._crud_secrets = crud_secrets
        self._cache = CrudCAAuthoritiesCache(log=log, coll=coll, protector=protector)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    @property
    def cache(self):
        return self._cache

    async def get(
        self,
        _id: str,
        fields: list,
        use_cache: bool = True,
    ) -> CAAuthorityGet:
        if use_cache and _id in self.cache.cache:
            return self.cache.cache[_id]
        result = await self._get(query={"id": _id}, fields=fields)
        return CAAuthorityGet(**result)

    async def get_private_key_cached(self, _id: str) -> bytes:
        if _id not in self.cache.key_cache:
            return await self.get_private_key(_id)
        return self.cache.key_cache[_id]

    async def get_all_internal_cas(self) -> list[str]:
        return [
            ca_id
            for ca_id, ca in self.cache.cache.items()
            if ca.internal and ca.status == "active"
        ]

    @property
    def protector(self):
        return self._protector

    async def _validate_validation_config(self, payload: dict) -> None:
        if payload.get("validation_config"):
            config = CAValidationConfig(**payload["validation_config"])
            await validate_secret_references(config, self._crud_secrets)

    async def find_referencing_ids(self, secret_id: str) -> list[str]:
        """Return ids of CA authorities whose validation_config references
        ``secret_id`` (used to block deletion of an in-use secret)."""
        referencing: list[str] = []
        cursor = self.coll.find({}, {"id": 1, "validation_config": 1})
        async for doc in cursor:
            raw = doc.get("validation_config")
            if not raw:
                continue
            config = CAValidationConfig(**raw)
            if secret_id in extract_references(config):
                referencing.append(doc["id"])
        return referencing

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

    async def create(
        self, _id: str, payload: CAAuthorityPostInternal, fields: list
    ) -> CAAuthorityGet:
        data = payload.model_dump()
        data["id"] = _id
        await self._validate_validation_config(data)
        result = await self._create(payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def update(
        self, _id: str, payload: CAAuthorityPutInternal, fields: list
    ) -> CAAuthorityGet:
        data = payload.model_dump(exclude_unset=True)
        await self._validate_validation_config(data)
        result = await self._update(query={"id": _id}, payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def resource_exists(self, _id: str) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def delete(self, _id: str) -> DataDelete:
        await self._delete(query={"id": _id})
        return DataDelete()

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_private_key(self, _id: str) -> bytes:
        result = await self._get(query={"id": _id}, fields=["private_key_encrypted"])
        decrypted = self._protector.decrypt_string(result["private_key_encrypted"])
        return decrypted.encode()

    async def get_revoked_for_ca(self, parent_id: str) -> list[dict]:
        cursor = self.coll.find(
            {
                "parent_id": parent_id,
                "status": "revoked",
                "serial_number": {"$exists": True},
            },
            {"serial_number": 1, "revocation_date": 1},
        )
        revoked = []
        async for ca in cursor:
            revoked.append(
                {
                    "serial_number": int(ca["serial_number"]),
                    "revocation_date": ca.get(
                        "revocation_date", datetime.datetime.now(datetime.timezone.utc)
                    ),
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
                        "crl.generation": current_generation + 1,
                    }
                },
            )
            if result.modified_count > 0:
                updated = await self.coll.find_one({"id": ca_id}, {"crl": 1})
                return CACRL(**updated["crl"])
