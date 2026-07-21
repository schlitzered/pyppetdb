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

import logging
import typing
from datetime import datetime, timezone

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_secrets import CASecretGet
from pyppetdb.model.ca_secrets import CASecretGetMulti
from pyppetdb.model.ca_secrets import CASecretPost
from pyppetdb.model.ca_secrets import CASecretPostInternal
from pyppetdb.model.ca_secrets import CASecretPut
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal


class CrudCASecrets(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        super().__init__(config, log, coll, schema_model=CASecretGet)
        self._protector = protector
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    @property
    def protector(self):
        return self._protector

    async def create(
        self, _id: str, payload: CASecretPost, fields: list
    ) -> CASecretGet:
        now = datetime.now(timezone.utc)
        internal = CASecretPostInternal(
            id=_id,
            secret_encrypted=self._protector.encrypt_string(payload.secret),
            description=payload.description,
            created=now,
            updated=now,
        )
        result = await self._create(payload=internal.model_dump(), fields=fields)
        return CASecretGet(**result)

    async def update(self, _id: str, payload: CASecretPut, fields: list) -> CASecretGet:
        data: dict = {"updated": datetime.now(timezone.utc)}
        if payload.secret is not None:
            data["secret_encrypted"] = self._protector.encrypt_string(payload.secret)
        if payload.description is not None:
            data["description"] = payload.description
        result = await self._update(query={"id": _id}, payload=data, fields=fields)
        return CASecretGet(**result)

    async def get(self, _id: str, fields: list) -> CASecretGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CASecretGet(**result)

    async def resource_exists(self, _id: str) -> ObjectId:
        return await self._resource_exists(query={"id": _id})

    async def exists(self, _id: str) -> bool:
        try:
            await self._resource_exists(query={"id": _id})
            return True
        except ResourceNotFound:
            return False

    async def existing_ids(self, ids: typing.Iterable[str]) -> set[str]:
        ids = list(ids)
        if not ids:
            return set()
        cursor = self.coll.find({"id": {"$in": ids}}, {"id": 1})
        return {doc["id"] async for doc in cursor}

    async def get_values(self, ids: typing.Iterable[str]) -> dict[str, str]:
        ids = list(ids)
        if not ids:
            return {}
        secret_map: dict[str, str] = {}
        cursor = self.coll.find({"id": {"$in": ids}}, {"id": 1, "secret_encrypted": 1})
        async for doc in cursor:
            encrypted = doc.get("secret_encrypted")
            if not encrypted:
                continue
            try:
                secret_map[doc["id"]] = self._protector.decrypt_string(encrypted)
            except Exception as err:
                self.log.error(f"Failed to decrypt CA secret {doc['id']}: {err}")
        return secret_map

    async def delete(self, _id: str) -> DataDelete:
        await self._delete(query={"id": _id})
        return DataDelete()

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        description: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CASecretGetMulti:
        query: dict = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "description", description)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CASecretGetMulti(**result)
