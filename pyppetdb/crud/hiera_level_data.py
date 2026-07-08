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
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.hiera_level_data import HieraLevelDataGet
from pyppetdb.model.hiera_level_data import HieraLevelDataGetMulti
from pyppetdb.model.hiera_level_data import HieraLevelDataPost
from pyppetdb.model.hiera_level_data import HieraLevelDataPut
from pyppetdb.helpers.hiera import HieraLevelFormatter


class CrudHieraLevelData(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super().__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._indices.append(
            pymongo.IndexModel(
                [
                    ("key_id", pymongo.ASCENDING),
                    ("id", pymongo.ASCENDING),
                    ("level_id", pymongo.ASCENDING),
                ],
                unique=True,
            )
        )
        self._indices.append(
            pymongo.IndexModel(
                [("key", pymongo.ASCENDING)],
            )
        )
        self._formatter = HieraLevelFormatter()

    async def _create_index(self) -> None:
        await super()._create_index()

    def _normalize_facts(self, level_id: str, facts: dict[str, str]) -> dict[str, str]:
        fields = [fname for _, fname, _, _ in self._formatter.parse(level_id) if fname]
        return {k: v for k, v in facts.items() if k in fields}

    def _validate_level_and_id(
        self,
        level_id: str,
        data_id: str,
        facts: dict[str, str],
    ):
        try:
            if not data_id == self._formatter.format(
                level_id,
                **facts,
            ):
                raise QueryParamValidationError(
                    msg=f"invalid data_id {data_id}, not matching expanded level_id {level_id}"
                )
        except KeyError as err:
            raise QueryParamValidationError(msg=f"missing fact {level_id}: {err}")

    async def create(
        self,
        _id: str,
        key_id: str,
        level_id: str,
        payload: HieraLevelDataPost,
        priority: int | None,
        fields: list,
    ) -> HieraLevelDataGet:
        data = payload.model_dump()
        self._validate_level_and_id(
            level_id=level_id,
            data_id=_id,
            facts=data["facts"],
        )
        data["id"] = _id
        data["key_id"] = key_id
        data["level_id"] = level_id
        data["priority"] = priority
        data["facts"] = self._normalize_facts(
            level_id=level_id,
            facts=data["facts"],
        )
        result = await self._create(
            payload=data,
            fields=fields,
        )
        return HieraLevelDataGet(**result)

    async def delete(
        self,
        _id: str,
        key_id: str,
        level_id: str,
    ) -> DataDelete:
        query = {
            "id": _id,
            "key_id": key_id,
            "level_id": level_id,
        }
        await self._delete(query=query)
        return DataDelete()

    async def delete_all_from_level(self, level_id: str):
        await self.coll.delete_many(
            filter={"level_id": level_id},
        )

    async def update_priority_by_level(
        self, level_id: str, priority: int | None
    ) -> None:
        await self.coll.update_many(
            filter={"level_id": level_id},
            update={"$set": {"priority": priority}},
        )

    async def delete_all_from_key(self, key_id: str):
        await self.coll.delete_many(
            filter={"key_id": key_id},
        )

    async def get(
        self,
        _id: str,
        key_id: str,
        level_id: str,
        fields: list,
    ) -> HieraLevelDataGet:
        query = {
            "id": _id,
            "key_id": key_id,
            "level_id": level_id,
        }
        result = await self._get(query=query, fields=fields)
        return HieraLevelDataGet(**result)

    async def resource_exists(
        self,
        _id: str,
        key_id: str,
        level_id: str,
    ):
        query = {
            "id": _id,
            "key_id": key_id,
            "level_id": level_id,
        }
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: Optional[str] = None,
        key_id: Optional[str] = None,
        level_id: Optional[str] = None,
        _id_list: Optional[list[str]] = None,
        fact: Optional[set[str]] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        query: Optional[dict] = None,
    ) -> HieraLevelDataGetMulti:
        if not query:
            query = {}
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_re(query, "id", _id)
        self._filter_re(query, "key_id", key_id)
        self._filter_re(query, "level_id", level_id)
        self._filter_list(query, "id", _id_list)
        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return HieraLevelDataGetMulti(**result)

    async def update(
        self,
        _id: str,
        key_id: str,
        level_id: str,
        payload: HieraLevelDataPut,
        fields: list,
        upsert: bool = False,
        return_none: bool = False,
    ) -> HieraLevelDataGet | None:
        query = {
            "id": _id,
            "key_id": key_id,
            "level_id": level_id,
        }
        data = payload.model_dump()
        result = await self._update(
            query=query,
            fields=fields,
            payload=data,
            upsert=upsert,
        )
        if return_none:
            return None
        return HieraLevelDataGet(**result)
