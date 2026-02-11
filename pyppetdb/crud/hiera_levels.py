import asyncio
import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_levels import HieraLevelGet
from pyppetdb.model.hiera_levels import HieraLevelGetMulti
from pyppetdb.model.hiera_levels import HieraLevelPost
from pyppetdb.model.hiera_levels import HieraLevelPut


class CrudHieraLevelsCache:
    def __init__(self, log: logging.Logger, coll: AsyncIOMotorCollection):
        self._coll = coll
        self._log = log
        self._cache = {}
        self._level_ids = []
        self._initialized = False

    @property
    def cache(self) -> dict["str", HieraLevelGet]:
        return self._cache

    @property
    def level_ids(self) -> list[str]:
        return self._level_ids

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    async def _watch_changes(self):
        try:
            pipeline = [
                {
                    "$project": {
                        "fullDocument.id": 1,
                        "operationType": 1,
                        "documentKey._id": 1,
                    }
                }
            ]

            async with self.coll.watch(
                full_document="updateLookup",
                pipeline=pipeline,
            ) as change_stream:
                self.log.info("Change stream watcher started for hiera_levels")
                async for change in change_stream:
                    await self._handle_change(change)

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error in hiera_levels change stream: {err}")
        except Exception as err:
            self.log.error(f"Unexpected error in hiera_levels change stream: {err}")

    async def _handle_change(self, change):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]

        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if doc:
                level_id = doc.get("id")
                if level_id is None:
                    self.log.warning(
                        f"No id in fullDocument for {operation} change {doc_id}"
                    )
                    return
                if level_id not in self._level_ids:
                    self._level_ids.append(level_id)
                self.cache[doc_id] = HieraLevelGet(**doc)
            else:
                self.log.warning(f"No fullDocument in {operation} change for {doc_id}")

        elif operation == "delete":
            doc = self.cache.pop(doc_id, None)
            level_id = doc.id if doc else None
            if level_id and level_id in self._level_ids:
                self._level_ids.remove(level_id)

        else:
            self.log.warning(f"Unhandled operation type: {operation}")

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({}, {"id": 1, "_id": 1})
            count = 0
            async for doc in cursor:
                doc_id = doc["_id"]
                level_id = doc.get("id")
                if level_id is None:
                    continue
                if doc_id not in self.cache:
                    self.cache[doc_id] = HieraLevelGet(**doc)
                    if level_id not in self._level_ids:
                        self._level_ids.append(level_id)
                    count += 1

            self.log.info(f"Loaded {count} initial documents into hiera_levels cache")

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error loading initial data: {err}")
            raise

    async def run(self):
        if self._initialized:
            return
        asyncio.create_task(self._watch_changes())
        await self._load_initial_data()
        self._initialized = True
        self.log.info("HieraLevelsCache initialized successfully")


class CrudHieraLevels(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudHieraLevels, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._cache = CrudHieraLevelsCache(log=log, coll=coll)

    @property
    def cache(self):
        return self._cache

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("priority", pymongo.ASCENDING)], unique=True)
        await self.cache.run()
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: HieraLevelPost,
        fields: list,
    ) -> HieraLevelGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return HieraLevelGet(**result)

    async def delete(
        self,
        _id: str,
    ) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> HieraLevelGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return HieraLevelGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        priority: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraLevelGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_literal(query, "priority", priority)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return HieraLevelGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: HieraLevelPut,
        fields: list,
    ) -> HieraLevelGet:
        query = {"id": _id}
        data = payload.model_dump()

        result = await self._update(query=query, fields=fields, payload=data)
        return HieraLevelGet(**result)
