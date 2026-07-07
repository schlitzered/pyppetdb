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
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import DataDelete
from pyppetdb.model.pyppetdb_nodes import PyppetDBNodeGet
from pyppetdb.model.pyppetdb_nodes import PyppetDBNodeGetMulti


class CrudPyppetDBNodes(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudPyppetDBNodes, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING)], unique=True, name="idx_id"
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()
        await self._create_ttl_index(
            field="heartbeat",
            ttl_seconds=70,
            index_name="ttl_heartbeat",
        )

    async def heartbeat_update(
        self,
        _id: str,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        await self.coll.update_one(
            filter={"id": _id},
            update={
                "$set": {"heartbeat": now},
                "$setOnInsert": {"online_since": now},
            },
            upsert=True,
        )

    async def delete(
        self,
        _id: str,
    ) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> PyppetDBNodeGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return PyppetDBNodeGet(**result)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[str] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> PyppetDBNodeGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return PyppetDBNodeGetMulti(**result)

    async def get_leader(self) -> str | None:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=60)
        query = {"heartbeat": {"$gt": threshold}}
        cursor = (
            self.coll.find(query)
            .sort([("online_since", pymongo.ASCENDING), ("id", pymongo.ASCENDING)])
            .limit(1)
        )
        async for doc in cursor:
            return str(doc.get("id"))
        return None
