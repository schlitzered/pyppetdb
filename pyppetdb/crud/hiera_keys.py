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
from pyppetdb.model.hiera_keys import HieraKeyGet
from pyppetdb.model.hiera_keys import HieraKeyGetMulti
from pyppetdb.model.hiera_keys import HieraKeyPost
from pyppetdb.model.hiera_keys import HieraKeyPut
from pyppetdb.pyhiera import PyHiera
from pyhiera.errors import PyHieraError


class CrudHieraKeysAdapter:
    def __init__(
        self,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        pyhiera: PyHiera,
    ):
        self._coll = coll
        self._log = log
        self._pyhiera = pyhiera
        self._doc_to_key = {}
        self._initialized = False

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    def _add_or_update_key(self, key_id: str, model_id: str):
        model_type = self._pyhiera.hiera.key_models.get(model_id)
        if not model_type:
            self.log.warning(f"key model {model_id} not found")
            return
        self._pyhiera.hiera.key_add(key_id, model_id)

    def _delete_key(self, key_id: str):
        try:
            self._pyhiera.hiera.key_delete(key_id)
        except PyHieraError as err:
            self.log.warning(f"failed to delete key {key_id}: {err}")

    async def _watch_changes(self):
        try:
            pipeline = [
                {
                    "$project": {
                        "fullDocument.id": 1,
                        "fullDocument.key_model_id": 1,
                        "operationType": 1,
                        "documentKey._id": 1,
                    }
                }
            ]

            async with self.coll.watch(
                full_document="updateLookup",
                pipeline=pipeline,
            ) as change_stream:
                self.log.info("Change stream watcher started for hiera_keys")
                async for change in change_stream:
                    await self._handle_change(change)

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error in hiera_keys change stream: {err}")
        except Exception as err:
            self.log.error(f"Unexpected error in hiera_keys change stream: {err}")

    async def _handle_change(self, change):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]

        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if not doc:
                self.log.warning(f"No fullDocument in {operation} change for {doc_id}")
                return
            key_id = doc.get("id")
            model_id = doc.get("key_model_id")
            if not key_id or not model_id:
                self.log.warning(f"Missing key id or model id for change {doc_id}")
                return
            self._add_or_update_key(key_id, model_id)
            self._doc_to_key[doc_id] = key_id

        elif operation == "delete":
            key_id = self._doc_to_key.pop(doc_id, None)
            if key_id:
                self._delete_key(key_id)

        else:
            self.log.warning(f"Unhandled operation type: {operation}")

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({}, {"id": 1, "key_model_id": 1, "_id": 1})
            count = 0
            async for doc in cursor:
                doc_id = doc["_id"]
                key_id = doc.get("id")
                model_id = doc.get("key_model_id")
                if not key_id or not model_id:
                    continue
                self._add_or_update_key(key_id, model_id)
                self._doc_to_key[doc_id] = key_id
                count += 1

            self.log.info(f"Loaded {count} initial documents into hiera_keys adapter")

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error loading initial data: {err}")
            raise

    async def run(self):
        if self._initialized:
            return
        asyncio.create_task(self._watch_changes())
        await self._load_initial_data()
        self._initialized = True
        self.log.info("HieraKeysAdapter initialized successfully")


class CrudHieraKeys(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        pyhiera: PyHiera,
    ):
        super(CrudHieraKeys, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._keys_adapter = CrudHieraKeysAdapter(log=log, coll=coll, pyhiera=pyhiera)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("key_model_id", pymongo.ASCENDING)])
        await self.coll.create_index([("deprecated", pymongo.ASCENDING)])
        await self._keys_adapter.run()
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: HieraKeyPost,
        fields: list,
    ) -> HieraKeyGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return HieraKeyGet(**result)

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
    ) -> HieraKeyGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return HieraKeyGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        model: typing.Optional[str] = None,
        deprecated: typing.Optional[bool] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraKeyGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "key_model_id", model)
        self._filter_boolean(query, "deprecated", deprecated)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return HieraKeyGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: HieraKeyPut,
        fields: list,
    ) -> HieraKeyGet:
        query = {"id": _id}
        data = payload.model_dump()
        result = await self._update(query=query, fields=fields, payload=data)
        return HieraKeyGet(**result)
