from pyppetdb.crud.common import CrudMongo
import typing
import pymongo
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.common import sort_order_literal

from motor.motor_asyncio import AsyncIOMotorCollection
from pyppetdb.config import Config
import logging
from pyppetdb.errors import QueryParamValidationError


class CrudCASpaces(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super().__init__(config, log, coll)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    async def insert(self, payload: dict, fields: list) -> CASpaceGet:
        result = await self._create(payload=payload, fields=fields)
        return CASpaceGet(**result)

    async def update(
        self, query: dict, payload: dict, fields: list, upsert: bool = False
    ) -> CASpaceGet:
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
