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

from pyppetdb.crud.common import CrudMongo
import asyncio
import typing
import pymongo
from pyppetdb.model.ca_spaces import CASpaceGet, CASpacePost
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.common import sort_order_literal

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorClientSession
from pyppetdb.config import Config
import logging
from typing import Optional
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.ca.validation_protector import CAValidationProtector
from pyppetdb.model.ca_validation import CAValidationConfig


class CrudCASpacesCache:
    def __init__(self, log: logging.Logger, coll: AsyncIOMotorCollection):
        self._coll = coll
        self._log = log
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

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({})
            async for doc in cursor:
                self._cache[doc["id"]] = CASpaceGet(**doc)
                self._doc_to_id[doc["_id"]] = doc["id"]
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
                            self._cache[doc["id"]] = CASpaceGet(**doc)
                            self._doc_to_id[doc_id] = doc["id"]
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
    ):
        super().__init__(config, log, coll, schema_model=CASpacePost)
        self._protector = protector
        self._cache = CrudCASpacesCache(log=log, coll=coll)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    @property
    def cache(self):
        return self._cache

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
        self, payload: dict, space_id: Optional[str] = None
    ):
        if "validation_config" in payload and payload["validation_config"]:
            protector = CAValidationProtector(self._protector)
            config = CAValidationConfig(**payload["validation_config"])

            if self._has_masks(config) and space_id:
                try:
                    current = await self.get(space_id, fields=["validation_config"])
                    if current.validation_config:
                        config = protector.merge_secrets(
                            config, current.validation_config
                        )
                except Exception:
                    pass

            encrypted = protector.encrypt_config(config)
            payload["validation_config"] = encrypted.model_dump()

    async def get_cached(self, _id: str) -> CASpaceGet:
        if _id not in self.cache.cache:
            return await self.get(_id, fields=None)
        return self.cache.cache[_id]

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

    async def insert(self, payload: dict, fields: list) -> CASpaceGet:
        await self._encrypt_validation_config(payload, space_id=payload.get("id"))
        result = await self._create(payload=payload, fields=fields)
        return CASpaceGet(**result)

    async def update(
        self, query: dict, payload: dict, fields: list, upsert: bool = False
    ) -> CASpaceGet:
        await self._encrypt_validation_config(payload, space_id=query.get("id"))
        result = await self._update(
            query=query, payload=payload, fields=fields, upsert=upsert
        )
        return CASpaceGet(**result)

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> CASpaceGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CASpaceGet(**result)

    async def resource_exists(self, _id: str) -> str:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def delete(self, query: dict) -> None:
        if query.get("id") == "puppet-ca":
            raise QueryParamValidationError(
                msg="The 'puppet-ca' space is protected and cannot be deleted"
            )
        await self._delete(query=query)

    async def remove_ca_from_history(self, ca_id: str) -> None:
        await self.coll.update_many(
            {"ca_id_history": ca_id}, {"$pull": {"ca_id_history": ca_id}}
        )

    async def search_by_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find({"$or": [{"ca_id": ca_id}, {"ca_id_history": ca_id}]})
        return await cursor.to_list(length=None)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        ca_id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
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
