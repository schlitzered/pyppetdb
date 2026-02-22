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

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [
                ("key_id", pymongo.ASCENDING),
                ("merge", pymongo.ASCENDING),
                ("facts.key", pymongo.ASCENDING),
                ("facts.value", pymongo.ASCENDING),
            ],
        )
        self.log.info(f"creating {self.resource_type} indices, done")

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
