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
from pyppetdb.model.hiera_keys import HieraKeyGet
from pyppetdb.model.hiera_keys import HieraKeyGetMulti
from pyppetdb.model.hiera_keys import HieraKeyPost
from pyppetdb.model.hiera_keys import HieraKeyPut


class CrudHieraKeys(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudHieraKeys, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("key_model_id", pymongo.ASCENDING)])
        await self.coll.create_index([("deprecated", pymongo.ASCENDING)])
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: HieraKeyPost,
        fields: list,
    ) -> HieraKeyGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return HieraKeyGet(**result)

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
    ) -> HieraKeyGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return HieraKeyGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        model: typing.Optional[str] = None,
        deprecated: typing.Optional[bool] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraKeyGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "key_model_id", model)
        self._filter_boolean(query, "deprecated", deprecated)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return HieraKeyGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: HieraKeyPut,
        fields: list,
    ) -> HieraKeyGet:
        query = {"id": _id}
        data = payload.model_dump()
        result = await self._update(query=query, fields=fields, payload=data)
        return HieraKeyGet(**result)
