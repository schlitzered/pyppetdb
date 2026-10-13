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
import typing
from typing import Optional
import pymongo
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorClientSession

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.watcher import CollectionWatcher
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.model.ca_authorities import (
    CAAuthorityCacheEntry,
    CAAuthorityGet,
    CAAuthorityPostInternal,
    CASigner,
    SignerSource,
)
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CAAuthorityPutInternal
from pyppetdb.model.ca_authorities import CACRL
from pyppetdb.model.ca_authorities import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import DataDelete
from pyppetdb.model.ca_secret_refs import secret_refs_of
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
        self._cache: dict[str, CAAuthorityCacheEntry] = {}
        self._doc_to_id = {}
        self._watcher = CollectionWatcher(
            coll=self.coll,
            log=self.log,
            name="ca_authorities",
            handle_change=self._handle_change,
            resync=self._load,
        )
        self._initialized = False

    @property
    def cache(self) -> dict[str, CAAuthorityCacheEntry]:
        return self._cache

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    @property
    def ready(self) -> bool:
        return self._watcher.ready

    async def run(self):
        if self._initialized:
            return
        await self._load_initial_data()
        self._watcher.start()
        self._initialized = True

    def get_signer(self, ca_id: str) -> Optional[CASigner]:
        if not self.ready:
            return None
        entry = self._cache.get(ca_id)
        if entry is None:
            return None
        return entry.signer

    def store_signer(self, ca_id: str, signer: CASigner) -> bool:
        if not self.ready:
            return False
        entry = self._cache.get(ca_id)
        if entry is None or entry.source is None or entry.source != signer.source:
            return False
        entry.signer = signer
        return True

    def _process_doc(self, doc: dict) -> CAAuthorityCacheEntry:
        entry = CAAuthorityCacheEntry(authority=CAAuthorityGet(**doc))
        if doc.get("private_key_encrypted"):
            try:
                decrypted = self._protector.decrypt_string(doc["private_key_encrypted"])
                entry.private_key = decrypted.encode()
            except Exception as e:
                self.log.error(
                    f"Failed to decrypt private key for CA {entry.authority.id}: {e}"
                )
        return entry

    def _put(self, entry: CAAuthorityCacheEntry) -> None:
        previous = self._cache.get(entry.authority.id)
        if (
            previous is not None
            and previous.signer is not None
            and entry.source is not None
            and previous.signer.source == entry.source
        ):
            entry.signer = previous.signer
        self._cache[entry.authority.id] = entry

    async def _load(self):
        doc_to_id = {}
        async for doc in self.coll.find({}):
            entry = self._process_doc(doc)
            self._put(entry)
            doc_to_id[doc["_id"]] = entry.authority.id
        for stale in set(self._cache) - set(doc_to_id.values()):
            self._cache.pop(stale, None)
        self._doc_to_id = doc_to_id
        self.log.info(f"Loaded {len(self._cache)} CA authorities into cache")

    async def _load_initial_data(self):
        try:
            await self._load()
        except Exception as e:
            self.log.error(f"Failed to load initial CA authorities: {e}")

    async def _handle_change(self, change: dict):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]
        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if doc:
                entry = self._process_doc(doc)
                self._put(entry)
                self._doc_to_id[doc_id] = entry.authority.id
        elif operation == "delete":
            custom_id = self._doc_to_id.pop(doc_id, None)
            if custom_id:
                self._cache.pop(custom_id, None)
                self.log.info(f"Removed CA authority {custom_id} from cache")
            else:
                await self._load()

    @property
    def watcher(self) -> CollectionWatcher:
        return self._watcher

    async def _watch_changes(self):
        await self._watcher.run()


class CrudCAAuthorities(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        super().__init__(config, log, coll, schema_model=CAAuthorityGet)
        self._protector = protector
        self._cache = CrudCAAuthoritiesCache(log=log, coll=coll, protector=protector)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )
        self._indices.append(
            pymongo.IndexModel(
                [("secret_refs", pymongo.ASCENDING)], name="idx_secret_refs"
            )
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
        if use_cache and self.cache.ready and _id in self.cache.cache:
            return self._project_model(self.cache.cache[_id].authority, fields)
        result = await self._get(query={"id": _id}, fields=fields)
        return CAAuthorityGet(**result)

    async def get_signer(self, _id: str) -> Optional[CASigner]:
        return self.cache.get_signer(_id)

    async def get_signer_source(self, _id: str) -> SignerSource:
        if self.cache.ready:
            entry = self.cache.cache.get(_id)
            if entry is not None and entry.source is not None:
                return entry.source
        result = await self._get(
            query={"id": _id}, fields=["certificate", "private_key_encrypted"]
        )
        decrypted = self._protector.decrypt_string(result["private_key_encrypted"])
        return result["certificate"], decrypted.encode()

    async def store_signer(self, _id: str, signer: CASigner) -> bool:
        return self.cache.store_signer(_id, signer)

    @property
    def protector(self):
        return self._protector

    @property
    def watcher(self) -> CollectionWatcher:
        return self.cache.watcher

    async def _create_index(self) -> None:
        await super()._create_index()
        await self.cache.run()

    async def migrate_1(
        self, session: Optional[AsyncIOMotorClientSession] = None
    ) -> None:
        await super().migrate_1(session=session)
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

    async def migrate_2(
        self, session: Optional[AsyncIOMotorClientSession] = None
    ) -> None:
        await super().migrate_2(session=session)
        cursor = self.coll.find(
            {"secret_refs": {"$exists": False}},
            {"validation_config": 1},
            session=session,
        )
        migrated = 0
        async for doc in cursor:
            config = CAValidationConfig(**(doc.get("validation_config") or {}))
            await self.coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"secret_refs": secret_refs_of(config)}},
                session=session,
            )
            migrated += 1
        if migrated > 0:
            self.log.info(f"Migrated {migrated} CA Authorities with secret references")

    async def create(
        self, _id: str, payload: CAAuthorityPostInternal, fields: list
    ) -> CAAuthorityGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def update(
        self, _id: str, payload: CAAuthorityPutInternal, fields: list
    ) -> CAAuthorityGet:
        data = payload.model_dump(exclude_unset=True)
        result = await self._update(query={"id": _id}, payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def revoke(self, _id: str, revocation_date: datetime.datetime) -> None:
        await self._update(
            query={"id": _id, "status": {"$ne": "revoked"}},
            payload={"status": "revoked", "revocation_date": revocation_date},
            fields=["id"],
        )

    async def resource_exists(self, _id: str) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def delete(self, _id: str) -> DataDelete:
        await self._delete(query={"id": _id})
        return DataDelete()

    async def search(
        self,
        _id: typing.Optional[str] = None,
        parent_id: typing.Optional[str] = None,
        cn: typing.Optional[str] = None,
        fingerprint: typing.Optional[str] = None,
        internal: typing.Optional[bool] = None,
        status: typing.Optional[CAStatus] = None,
        secret_ref: typing.Optional[str] = None,
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
        self._filter_literal(query, "secret_refs", secret_ref)

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
