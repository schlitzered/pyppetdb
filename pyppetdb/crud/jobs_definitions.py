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

from typing import Optional

import pymongo
from bson.objectid import ObjectId

from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_definitions import JobDefinitionGet
from pyppetdb.model.jobs_definitions import JobDefinitionGetMulti
from pyppetdb.model.jobs_definitions import JobDefinitionPost
from pyppetdb.model.jobs_definitions import JobDefinitionPut
from pyppetdb.model.common import DataDelete


class CrudJobsDefinitions(CrudMongo):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._indices.append(
            pymongo.IndexModel([("id", pymongo.ASCENDING)], unique=True, name="idx_id")
        )

    async def _create_index(self) -> None:
        await super()._create_index()

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

    async def resource_exists(self, _id: str) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

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
        _id: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
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
