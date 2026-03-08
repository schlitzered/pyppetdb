from pyppetdb.crud.common import CrudMongo
import typing
import pymongo
from pyppetdb.model.ca_spaces import (
    CASpacePost, CASpaceGet, CASpaceGetMulti
)
from pyppetdb.model.common import sort_order_literal

class CrudCASpaces(CrudMongo):
    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")
    async def create(self, payload: CASpacePost, fields: list[str] = []) -> CASpaceGet:
        data = payload.model_dump()
        result = await self._create(payload=data, fields=fields)
        return CASpaceGet(**result)

    async def get(self, _id: str, fields: list[str] = []) -> CASpaceGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CASpaceGet(**result)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        authority_id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CASpaceGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "authority_id", authority_id)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CASpaceGetMulti(**result)
