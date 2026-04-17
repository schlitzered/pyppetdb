import logging
import typing
import uuid
from datetime import datetime

import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.jobs_jobs import (
    JobGet,
    JobGetMulti,
    JobPost,
)


class CrudJobs(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super().__init__(config=config, log=log, coll=coll)

    async def index_create(self) -> None:
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("definition_id", pymongo.ASCENDING)])
        await self.coll.create_index([("created_by", pymongo.ASCENDING)])
        await self.coll.create_index([("created_at", pymongo.ASCENDING)])

    async def create(
        self, payload: JobPost, node_ids: list[str], created_by: str, fields: list
    ) -> JobGet:
        job_id = str(uuid.uuid4())

        data = payload.model_dump()
        data["id"] = job_id
        data["nodes"] = node_ids
        data["created_at"] = datetime.now()
        data["created_by"] = created_by
        data["node_filter"] = list(payload.node_filter)

        result = await self._create(
            payload=data,
            fields=fields,
        )

        return JobGet(**result)

    async def remove_node_from_jobs(self, node_id: str):
        await self.coll.update_many(
            filter={"nodes": node_id},
            update={"$pull": {"nodes": node_id}},
        )

    async def get(self, _id: str, fields: list) -> JobGet:
        query = {"id": _id}
        result = await self._get(
            query=query,
            fields=fields,
        )
        return JobGet(**result)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        definition_id: typing.Optional[str] = None,
        created_by: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> JobGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "definition_id", definition_id)
        self._filter_re(query, "created_by", created_by)
        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return JobGetMulti(**result)
