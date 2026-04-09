import logging
import typing
from datetime import datetime

import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import DataDelete
from pyppetdb.model.pyppetdb_nodes import PyppetDBNodeGet, PyppetDBNodeGetMulti


class CrudPyppetDBNodes(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudPyppetDBNodes, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("heartbeat", pymongo.ASCENDING)])
        self.log.info(f"creating {self.resource_type} indices, done")

    async def heartbeat_update(self, _id: str) -> None:
        now = datetime.now()
        await self.coll.update_one(
            filter={"id": _id},
            update={"$set": {"heartbeat": now}},
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
