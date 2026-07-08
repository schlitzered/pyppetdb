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

import datetime
from typing import List
from typing import Optional

import pymongo

from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_nodes_jobs import NodeJobGet
from pyppetdb.model.jobs_nodes_jobs import JobsNodeJobGetMulti


class CrudJobsNodeJobs(CrudMongo):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING)], unique=True, name="idx_id"
                ),
                pymongo.IndexModel([("job_id", pymongo.ASCENDING)], name="idx_job_id"),
                pymongo.IndexModel(
                    [("node_id", pymongo.ASCENDING)], name="idx_node_id"
                ),
                pymongo.IndexModel(
                    [("definition_id", pymongo.ASCENDING)], name="idx_definition_id"
                ),
                pymongo.IndexModel(
                    [("created_by", pymongo.ASCENDING)], name="idx_created_by"
                ),
                pymongo.IndexModel(
                    [("job_id", pymongo.ASCENDING), ("node_id", pymongo.ASCENDING)],
                    unique=True,
                    name="idx_job_node_uniqueness",
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()

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
        now = datetime.datetime.now()
        docs = [
            {
                "id": f"{job_id}:{node_id}",
                "job_id": job_id,
                "definition_id": definition_id,
                "node_id": node_id,
                "status": "scheduled",
                "created_by": created_by,
                "created_at": now,
            }
            for node_id in node_ids
        ]
        await self.coll.insert_many(documents=docs)

    async def expire_scheduled_jobs(self, timeout_seconds: int) -> List[NodeJobGet]:
        threshold = datetime.datetime.now() - datetime.timedelta(
            seconds=timeout_seconds
        )
        query = {"status": "scheduled", "created_at": {"$lt": threshold}}

        expired_jobs = []
        async for doc in self.coll.find(filter=query):
            expired_jobs.append(NodeJobGet(**self._format(doc)))

        if expired_jobs:
            await self.coll.update_many(
                filter=query,
                update={"$set": {"status": "failed"}},
            )

        return expired_jobs

    async def cancel_node_jobs(self, job_id: str):
        await self.coll.update_many(
            filter={"job_id": job_id, "status": "scheduled"},
            update={"$set": {"status": "canceled"}},
        )

    async def get_oldest_scheduled(self, node_id: str) -> Optional[NodeJobGet]:
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
        job_id: Optional[str] = None,
        node_id: Optional[str] = None,
        status: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
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
