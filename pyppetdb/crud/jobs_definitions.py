import typing
import pymongo
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_definitions import (
    JobDefinitionGet,
    JobDefinitionGetMulti,
    JobDefinitionPost,
    JobDefinitionPut,
)
from pyppetdb.model.common import DataDelete


class CrudJobsDefinitions(CrudMongo):
    async def index_create(self) -> None:
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)

    async def create(
        self, payload: JobDefinitionPost, fields: list
    ) -> JobDefinitionGet:
        data = payload.model_dump()
        result = await self._create(payload=data, fields=fields)
        return JobDefinitionGet(**result)

    async def get(self, _id: str, fields: list) -> JobDefinitionGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return JobDefinitionGet(**result)

    async def update(
        self, _id: str, payload: JobDefinitionPut, fields: list
    ) -> JobDefinitionGet:
        query = {"id": _id}
        data = payload.model_dump(exclude_unset=True)
        result = await self._update(query=query, payload=data, fields=fields)
        return JobDefinitionGet(**result)

    async def delete(self, _id: str) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def search(
        self,
        _id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[str] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> JobDefinitionGetMulti:
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
        return JobDefinitionGetMulti(**result)
