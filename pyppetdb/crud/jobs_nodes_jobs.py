import typing
import pymongo
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_nodes_jobs import (
    NodeJobGet,
    JobsNodeJobGetMulti,
)


class CrudJobsNodeJobs(CrudMongo):
    async def index_create(self) -> None:
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("job_id", pymongo.ASCENDING)])
        await self.coll.create_index([("node_id", pymongo.ASCENDING)])
        await self.coll.create_index([("job_id", 1), ("node_id", 1)], unique=True)

    async def create_node_job(self, job_id: str, node_id: str):
        await self.create_node_jobs(
            job_id=job_id,
            node_ids=[node_id],
        )

    async def create_node_jobs(self, job_id: str, node_ids: list[str]):
        if not node_ids:
            return
        docs = [
            {
                "id": f"{job_id}:{node_id}",
                "job_id": job_id,
                "node_id": node_id,
                "status": "scheduled",
                "log_blobs": [],
            }
            for node_id in node_ids
        ]
        await self.coll.insert_many(documents=docs)

    async def cancel_node_jobs(self, job_id: str):
        await self.coll.update_many(
            filter={"job_id": job_id, "status": "scheduled"},
            update={"$set": {"status": "canceled"}},
        )

    async def get(self, _id: str, fields: list) -> NodeJobGet:
        query = {"id": _id}
        result = await self._get(
            query=query,
            fields=fields,
        )
        return NodeJobGet(**result)

    async def search(
        self,
        job_id: typing.Optional[str] = None,
        node_id: typing.Optional[str] = None,
        status: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[str] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> JobsNodeJobGetMulti:
        query = {}
        self._filter_re(query, "job_id", job_id)
        self._filter_re(query, "node_id", node_id)
        self._filter_literal(query, "status", status)
        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return JobsNodeJobGetMulti(**result)
