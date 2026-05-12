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
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo


class CrudHieraLookupCache(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudHieraLookupCache, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._indices.append(
            pymongo.IndexModel(
                [
                    ("key_id", pymongo.ASCENDING),
                    ("merge", pymongo.ASCENDING),
                    ("facts.key", pymongo.ASCENDING),
                    ("facts.value", pymongo.ASCENDING),
                ],
                name="idx_lookup_cache",
            )
        )

    async def _create_index(self) -> None:
        await super()._create_index()

    @staticmethod
    def _normalize_facts(facts: dict[str, str]) -> list[dict[str, str]]:
        return [{"key": key, "value": value} for key, value in sorted(facts.items())]

    async def get_cached(
        self,
        key_id: str,
        facts: dict[str, str],
        merge: bool,
    ) -> dict | None:
        query = {
            "key_id": key_id,
            "merge": merge,
            "facts": self._normalize_facts(facts),
        }
        result = await self.coll.find_one(filter=query)
        if result is None:
            return None
        return self._format(result)

    async def set_cached(
        self,
        key_id: str,
        facts: dict[str, str],
        merge: bool,
        result: dict[str, Any],
    ) -> None:
        query = {
            "key_id": key_id,
            "merge": merge,
            "facts": self._normalize_facts(facts),
        }
        payload = {
            "key_id": key_id,
            "merge": merge,
            "facts": self._normalize_facts(facts),
            "result": result,
        }
        await self.coll.update_one(filter=query, update={"$set": payload}, upsert=True)

    async def delete_by_key_and_facts(
        self,
        key_id: str,
        facts: dict[str, str] | None,
    ) -> None:
        normalized_facts = self._normalize_facts(facts or {})
        if normalized_facts:
            query = {
                "key_id": key_id,
                "facts": {"$all": normalized_facts},
            }
        else:
            query = {"key_id": key_id}
        await self.coll.delete_many(filter=query)

    async def clear_all(self) -> None:
        await self.coll.delete_many(filter={})
