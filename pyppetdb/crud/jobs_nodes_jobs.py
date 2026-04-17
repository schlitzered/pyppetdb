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
        await self.coll.create_index([("definition_id", pymongo.ASCENDING)])
        await self.coll.create_index([("created_by", pymongo.ASCENDING)])
        await self.coll.create_index([("job_id", 1), ("node_id", 1)], unique=True)

    async def create_node_job(
        self, job_id: str, definition_id: str, node_id: str, created_by: str
    ):
        await self.create_node_jobs(
            job_id=job_id,
            definition_id=definition_id,
            node_ids=[node_id],
            created_by=created_by,
        )

    async def create_node_jobs(
        self, job_id: str, definition_id: str, node_ids: list[str], created_by: str
    ):
        if not node_ids:
            return
        docs = [
            {
                "id": f"{job_id}:{node_id}",
                "job_id": job_id,
                "definition_id": definition_id,
                "node_id": node_id,
                "status": "scheduled",
                "created_by": created_by,
            }
            for node_id in node_ids
        ]
        await self.coll.insert_many(documents=docs)

    async def get_busy_nodes_for_definition(
        self, definition_id: str, node_ids: list[str]
    ) -> list[str]:
        cursor = self.coll.find(
            filter={
                "definition_id": definition_id,
                "node_id": {"$in": node_ids},
                "status": {"$in": ["scheduled", "running"]},
            },
            projection=["node_id"],
        )
        result = await cursor.to_list(length=None)
        return [doc["node_id"] for doc in result]

    async def cancel_node_jobs(self, job_id: str):
        await self.coll.update_many(
            filter={"job_id": job_id, "status": "scheduled"},
            update={"$set": {"status": "canceled"}},
        )

    async def get_oldest_scheduled(self, node_id: str) -> typing.Optional[NodeJobGet]:
        cursor = self.coll.find(filter={"node_id": node_id, "status": "scheduled"})
        cursor.sort([("_id", pymongo.ASCENDING)])
        result = await cursor.to_list(length=1)
        if result:
            return NodeJobGet(**self._format(result[0]))
        return None

    async def update_status(
        self,
        job_id: str,
        node_id: str,
        status: str,
    ):
        await self.coll.update_one(
            filter={"job_id": job_id, "node_id": node_id},
            update={"$set": {"status": status}},
        )

    async def delete_by_node(self, node_id: str):
        await self.coll.delete_many(filter={"node_id": node_id})

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
