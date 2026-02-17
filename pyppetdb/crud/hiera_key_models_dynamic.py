import logging
import typing

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyhiera.keys import PyHieraKeyBase
from pyhiera.errors import PyHieraError

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGet
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGetMulti
from pyppetdb.model.hiera_key_models_dynamic import HieraKeyModelDynamicPost
from pyppetdb.pyhiera import PyHiera
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX
from pyppetdb.pyhiera.schema_model_factory import SchemaModelFactory


class CrudHieraKeyModelsDynamic(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        pyhiera: PyHiera,
        schema_factory: SchemaModelFactory,
    ):
        super(CrudHieraKeyModelsDynamic, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._pyhiera = pyhiera
        self._schema_factory = schema_factory

    @property
    def pyhiera(self) -> PyHiera:
        return self._pyhiera

    @property
    def schema_factory(self) -> SchemaModelFactory:
        return self._schema_factory

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    def _build_key_model_class(
        self, model_id: str, schema: dict, description: str | None
    ) -> type[PyHieraKeyBase]:
        from pyhiera.models import PyHieraModelDataBase
        from pydantic import create_model
        from typing import Any

        raw_id = model_id
        if raw_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            raw_id = raw_id[len(KEY_MODEL_DYNAMIC_PREFIX) :]
        model_name = f"Dynamic_{raw_id}"

        # Create the validation model from the schema for validation only
        validation_model = self.schema_factory.create(schema, name=f"{model_name}_Validator")

        # Create a wrapper model that has a 'data' field typed as the schema model
        # but allows dict input. This makes dynamic models consistent with static models.
        wrapped_model = create_model(
            model_name,
            __base__=PyHieraModelDataBase,
            data=(Any, ...)  # Use Any to allow dict input/output
        )

        desc = description or "dynamic model"

        class DynamicKeyModel(PyHieraKeyBase):
            def __init__(self):
                super().__init__()
                self._description = desc
                self._model = wrapped_model
                self._validation_model = validation_model

            def validate(self, data: Any) -> PyHieraModelDataBase:
                # Validate the data against the schema first
                validated = self._validation_model(**data if isinstance(data, dict) else data)
                # Return it wrapped in the model with 'data' field as a dict
                return self._model(data=validated.model_dump())

        DynamicKeyModel.__name__ = model_name
        return DynamicKeyModel

    def _register_model(self, model_id: str, schema: dict, description: str | None):
        key_model_id = model_id
        if not key_model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            key_model_id = f"{KEY_MODEL_DYNAMIC_PREFIX}{key_model_id}"
        model_type = self._build_key_model_class(model_id, schema, description)
        try:
            self.pyhiera.hiera.key_model_delete(key_model_id)
        except PyHieraError:
            pass
        self.pyhiera.hiera.key_model_add(key_model_id, model_type)

    def _unregister_model(self, model_id: str):
        key_model_id = model_id
        if not key_model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            key_model_id = f"{KEY_MODEL_DYNAMIC_PREFIX}{key_model_id}"
        try:
            self.pyhiera.hiera.key_model_delete(key_model_id)
        except PyHieraError:
            pass

    async def load_all(self) -> None:
        cursor = self.coll.find({}, {"id": 1, "description": 1, "model": 1})
        async for doc in cursor:
            model_id = doc.get("id")
            schema = doc.get("model")
            if not model_id or not schema:
                continue
            self._register_model(model_id, schema, doc.get("description"))

    async def create(
        self,
        _id: str,
        payload: HieraKeyModelDynamicPost,
        fields: list,
    ) -> HieraKeyModelGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        self._register_model(_id, data["model"], data.get("description"))
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
        self._unregister_model(_id)
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
