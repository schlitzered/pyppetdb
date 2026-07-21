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

import asyncio
import logging
from typing import Optional

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from motor.motor_asyncio import AsyncIOMotorClientSession
import pymongo

from pyppetdb.ca.config_validation import validate_secret_references
from pyppetdb.ca.secret_resolver import extract_references
from pyppetdb.config import Config
from pyppetdb.crud.ca_secrets import CrudCASecrets
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_spaces import CASpaceGet, CASpacePost
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.ca_spaces import CASpacePutInternal
from pyppetdb.model.ca_validation import CAValidationConfig
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import DataDelete


class CrudCASpacesCache:
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
        self._doc_to_id = {}
        self._initialized = False

    @property
    def cache(self) -> dict["str", CASpaceGet]:
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

    def _process_doc(self, doc: dict) -> CASpaceGet:
        return CASpaceGet(**doc)

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({})
            async for doc in cursor:
                obj = self._process_doc(doc)
                self._cache[obj.id] = obj
                self._doc_to_id[doc["_id"]] = obj.id
            self.log.info(f"Loaded {len(self._cache)} initial CA spaces into cache")
        except Exception as e:
            self.log.error(f"Failed to load initial CA spaces: {e}")

    async def _watch_changes(self):
        try:
            async with self.coll.watch(full_document="updateLookup") as change_stream:
                self.log.info("Change stream watcher started for CA spaces")
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
                            self.log.info(f"Removed CA space {custom_id} from cache")
                        else:
                            await self._load_initial_data()
        except Exception as e:
            self.log.error(f"Error in CA spaces change stream: {e}")
            await asyncio.sleep(5)
            asyncio.create_task(self._watch_changes())


class CrudCASpaces(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
        crud_secrets: CrudCASecrets,
    ):
        super().__init__(config, log, coll, schema_model=CASpacePost)
        self._protector = protector
        self._crud_secrets = crud_secrets
        self._cache = CrudCASpacesCache(log=log, coll=coll, protector=protector)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    @property
    def cache(self):
        return self._cache

    @property
    def protector(self):
        return self._protector

    async def _validate_validation_config(self, payload: dict) -> None:
        if payload.get("validation_config"):
            config = CAValidationConfig(**payload["validation_config"])
            await validate_secret_references(config, self._crud_secrets)

    async def find_referencing_ids(self, secret_id: str) -> list[str]:
        """Return ids of CA spaces whose validation_config references
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

    async def get(
        self,
        _id: str,
        fields: list,
        use_cache: bool = True,
    ) -> CASpaceGet:
        if use_cache and _id in self.cache.cache:
            return self.cache.cache[_id]
        result = await self._get(query={"id": _id}, fields=fields)
        return CASpaceGet(**result)

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
                f"Migrated {res.modified_count} CA Spaces with default validation config"
            )

    async def create(self, _id: str, payload: CASpacePost, fields: list) -> CASpaceGet:
        data = payload.model_dump()
        data["id"] = _id
        await self._validate_validation_config(data)
        result = await self._create(payload=data, fields=fields)
        return CASpaceGet(**result)

    async def update(
        self, _id: str, payload: CASpacePutInternal, fields: list
    ) -> CASpaceGet:
        data = payload.model_dump(exclude_unset=True)
        await self._validate_validation_config(data)
        result = await self._update(query={"id": _id}, payload=data, fields=fields)
        return CASpaceGet(**result)

    async def resource_exists(self, _id: str) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def delete(self, _id: str) -> DataDelete:
        if _id == "puppet-ca":
            raise QueryParamValidationError(
                msg="The 'puppet-ca' space is protected and cannot be deleted"
            )
        await self._delete(query={"id": _id})
        return DataDelete()

    async def remove_ca_from_history(self, ca_id: str) -> None:
        await self.coll.update_many(
            {"ca_id_history": ca_id}, {"$pull": {"ca_id_history": ca_id}}
        )

    async def search_by_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find({"$or": [{"ca_id": ca_id}, {"ca_id_history": ca_id}]})
        return await cursor.to_list(length=None)

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def search(
        self,
        _id: Optional[str] = None,
        ca_id: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> CASpaceGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "ca_id", ca_id)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CASpaceGetMulti(**result)
