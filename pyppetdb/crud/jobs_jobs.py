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

import logging
import uuid
import datetime
import typing
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_jobs import JobGet
from pyppetdb.model.jobs_jobs import JobGetMulti
from pyppetdb.model.jobs_jobs import JobPost


class CrudJobs(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super().__init__(config=config, log=log, coll=coll)
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING)], unique=True, name="idx_id"
                ),
                pymongo.IndexModel(
                    [("definition_id", pymongo.ASCENDING)], name="idx_definition_id"
                ),
                pymongo.IndexModel(
                    [("created_by", pymongo.ASCENDING)], name="idx_created_by"
                ),
                pymongo.IndexModel(
                    [("created_at", pymongo.ASCENDING)], name="idx_created_at"
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()

    async def create(
        self, payload: JobPost, node_ids: list[str], created_by: str, fields: list
    ) -> JobGet:
        job_id = str(uuid.uuid4())
        data = {
            "id": job_id,
            "definition_id": payload.definition_id,
            "node_ids": node_ids,
            "created_by": created_by,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        result = await self._create(payload=data, fields=fields)
        return JobGet(**result)

    async def get(self, _id: str, fields: list) -> JobGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return JobGet(**result)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        definition_id: typing.Optional[str] = None,
        created_by: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[str] = None,
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
