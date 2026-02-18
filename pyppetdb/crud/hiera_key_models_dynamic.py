import asyncio
import logging
import typing

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyhiera.keys import PyHieraKeyBase
from pyhiera.errors import PyHieraError

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGet
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGetMulti
from pyppetdb.model.hiera_key_models_dynamic import HieraKeyModelDynamicPost
from pyppetdb.pyhiera import PyHiera
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX
from pyppetdb.pyhiera.schema_model_factory import SchemaModelFactory


class CrudHieraModelsDynamicAdapter:
    def __init__(
        self,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        pyhiera: PyHiera,
    ):
        self._coll = coll
        self._doc_to_model_id = {}
        self._log = log
        self._pyhiera = pyhiera
        self._initialized = False

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    @property
    def pyhiera(self):
        return self._pyhiera

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
                self.log.info(
                    "Change stream watcher started for hiera_key_models_dynamic"
                )
                async for change in change_stream:
                    await self._handle_change(change)

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error in hiera_key_models_dynamic change stream: {err}")
        except Exception as err:
            self.log.error(
                f"Unexpected error in hiera_key_models_dynamic change stream: {err}"
            )

    async def _handle_change(self, change):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]

        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if doc:
                model_id = doc.get("id")
                self.model_register(model_id, doc["model"], doc.get("description"))
                self._doc_to_model_id[doc_id] = model_id
            else:
                self.log.warning(f"No fullDocument in {operation} change for {doc_id}")

        elif operation == "delete":
            model_id = self._doc_to_model_id.pop(doc_id, None)
            if model_id:
                self.model_unregister(model_id)

        else:
            self.log.warning(f"Unhandled operation type: {operation}")

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find(
                {}, {"id": 1, "_id": 1, "description": 1, "model": 1}
            )
            count = 0
            async for doc in cursor:
                doc_id = doc["_id"]
                model_id = doc.get("id")
                if doc_id not in self._doc_to_model_id:
                    self._doc_to_model_id[doc_id] = model_id
                    self.model_register(model_id, doc["model"], doc.get("description"))
                    count += 1

            self.log.info(
                f"Loaded {count} initial documents for hiera_key_models_dynamic sync"
            )

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error loading initial data: {err}")
            raise

    def _build_key_model_class(
        self, model_id: str, schema: dict, description: str
    ) -> type[PyHieraKeyBase]:
        from pyhiera.models import PyHieraModelDataBase
        from pydantic import create_model
        from typing import Any

        validation_model = SchemaModelFactory().create(
            schema, name=f"{model_id}_Validator"
        )

        wrapped_model = create_model(
            model_id,
            __base__=PyHieraModelDataBase,
            data=(Any, ...),  # Use Any to allow dict input/output
        )

        class DynamicKeyModel(PyHieraKeyBase):
            def __init__(self):
                super().__init__()
                self._description = description
                self._model = wrapped_model
                self._validation_model = validation_model

            def validate(self, data: Any) -> PyHieraModelDataBase:
                validated = self._validation_model(
                    **data if isinstance(data, dict) else data
                )
                return self._model(data=validated.model_dump())

        DynamicKeyModel.__name__ = model_id
        return DynamicKeyModel

    def model_register(self, model_id: str, schema: dict, description: str):
        model_type = self._build_key_model_class(model_id, schema, description)
        try:
            self.pyhiera.hiera.key_model_delete(model_id)
        except PyHieraError:
            pass
        self.pyhiera.hiera.key_model_add(model_id, model_type)

    def model_unregister(self, model_id: str):
        self.pyhiera.hiera.key_model_delete(model_id)

    async def run(self):
        if self._initialized:
            return
        asyncio.create_task(self._watch_changes())
        await self._load_initial_data()
        self._initialized = True
        self.log.info("HieraKeyModelDynamicSync initialized successfully")


class CrudHieraKeyModelsDynamic(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        pyhiera: PyHiera,
    ):
        super(CrudHieraKeyModelsDynamic, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._key_model_adapter = CrudHieraModelsDynamicAdapter(
            log=log,
            coll=coll,
            pyhiera=pyhiera,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self._key_model_adapter.run()
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: HieraKeyModelDynamicPost,
        fields: list,
    ) -> HieraKeyModelGet:
        if not _id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            raise QueryParamValidationError(msg=f"key model {_id} not found")
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        self._key_model_adapter.model_register(
            _id, data["model"], data.get("description")
        )
        return HieraKeyModelGet(**result)

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> HieraKeyModelGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return HieraKeyModelGet(**result)

    async def delete(
        self,
        _id: str,
    ):
        query = {"id": _id}
        await self._delete(query=query)
        self._key_model_adapter.model_unregister(_id)
        return {}

    async def search(
        self,
        _id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraKeyModelGetMulti:
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
        return HieraKeyModelGetMulti(**result)
