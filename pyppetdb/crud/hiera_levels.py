import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_levels import HieraLevelGet
from pyppetdb.model.hiera_levels import HieraLevelGetMulti
from pyppetdb.model.hiera_levels import HieraLevelPost
from pyppetdb.model.hiera_levels import HieraLevelPut

PRIORITY_STEP = 10


class CrudHieraLevels(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudHieraLevels, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("priority", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: HieraLevelPost,
        fields: list,
    ) -> HieraLevelGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return HieraLevelGet(**result)

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
    ) -> HieraLevelGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return HieraLevelGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        priority: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraLevelGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_literal(query, "priority", priority)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return HieraLevelGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: HieraLevelPut,
        fields: list,
    ) -> HieraLevelGet:
        query = {"id": _id}
        data = payload.model_dump()

        result = await self._update(query=query, fields=fields, payload=data)
        return HieraLevelGet(**result)
