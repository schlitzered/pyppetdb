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

import typing
import pymongo

from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_definitions import JobDefinitionGet
from pyppetdb.model.jobs_definitions import JobDefinitionGetMulti
from pyppetdb.model.jobs_definitions import JobDefinitionPost
from pyppetdb.model.jobs_definitions import JobDefinitionPut
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

    async def resource_exists(self, _id: str) -> str:
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
