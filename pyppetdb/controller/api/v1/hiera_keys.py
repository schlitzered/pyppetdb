import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_STATIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import split_key_model_id
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_keys import filter_list
from pyppetdb.model.hiera_keys import filter_literal
from pyppetdb.model.hiera_keys import sort_literal
from pyppetdb.model.hiera_keys import HieraKeyGet
from pyppetdb.model.hiera_keys import HieraKeyGetMulti
from pyppetdb.model.hiera_keys import HieraKeyPost
from pyppetdb.model.hiera_keys import HieraKeyPut
from pyppetdb.pyhiera import PyHiera


class ControllerApiV1HieraKeys:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
        crud_hiera_key_models_dynamic: CrudHieraKeyModelsDynamic,
        crud_hiera_keys: CrudHieraKeys,
        crud_hiera_level_data: CrudHieraLevelData,
        pyhiera: PyHiera,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models_static = crud_hiera_key_models_static
        self._crud_hiera_key_models_dynamic = crud_hiera_key_models_dynamic
        self._crud_hiera_keys = crud_hiera_keys
        self._crud_hiera_level_data = crud_hiera_level_data
        self._pyhiera = pyhiera
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/keys",
            tags=["hiera_keys"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=HieraKeyGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{key_id}",
            self.create,
            response_model=HieraKeyGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{key_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{key_id}",
            self.get,
            response_model=HieraKeyGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{key_id}",
            self.update,
            response_model=HieraKeyGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_hiera_key_models_static(self):
        return self._crud_hiera_key_models_static

    @property
    def crud_hiera_key_models_dynamic(self):
        return self._crud_hiera_key_models_dynamic

    @property
    def crud_hiera_keys(self):
        return self._crud_hiera_keys

    @property
    def crud_hiera_level_data(self):
        return self._crud_hiera_level_data

    @property
    def pyhiera(self):
        return self._pyhiera

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def _key_model_exists(self, model_id: str) -> str:
        if model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            await self.crud_hiera_key_models_dynamic.get(_id=model_id, fields=["id"])
            return model_id
        self.crud_hiera_key_models_static.get(_id=model_id, fields=["id"])
        return model_id

    async def _validate_key_data(self, model_id: str, data):
        normalized_id = await self._key_model_exists(model_id)
        model_type = self.pyhiera.hiera.key_models.get(normalized_id)
        if not model_type:
            raise QueryParamValidationError(msg=f"key model {normalized_id} not found")
        try:
            model_type().validate(data)
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"invalid data for key model {normalized_id}: {err}"
            )

    async def create(
        self,
        request: Request,
        data: HieraKeyPost,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        await self._key_model_exists(data.key_model_id)
        return await self.crud_hiera_keys.create(
            _id=key_id,
            payload=data,
            fields=list(fields),
        )

    async def delete(
        self,
        request: Request,
        key_id: str,
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_keys.delete(_id=key_id)

    async def get(
        self,
        key_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_keys.get(_id=key_id, fields=list(fields))

    async def search(
        self,
        request: Request,
        key_id: str = Query(description="filter: regular_expressions", default=None),
        key_model_id: str = Query(
            description="filter: regular_expressions", default=None
        ),
        deprecated: bool = Query(default=None),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="id"),
        sort_order: sort_order_literal = Query(default="ascending"),
        page: int = Query(default=0, ge=0, description="pagination index"),
        limit: int = Query(
            default=10,
            ge=10,
            le=1000,
            description="pagination limit, min value 10, max value 1000",
        ),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_keys.search(
            _id=key_id,
            model=key_model_id,
            deprecated=deprecated,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        data: HieraKeyPut,
        key_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        current = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        new_model = data.key_model_id
        current_model = current.key_model_id
        if new_model:
            await self._key_model_exists(new_model)
        if new_model and new_model != current_model:
            level_data = await self.crud_hiera_level_data.search(
                key_id=key_id,
                level_id=".*",
                fields=["data"],
            )
            for item in level_data.result:
                await self._validate_key_data(new_model, item.data)
        return await self.crud_hiera_keys.update(
            _id=key_id,
            payload=data,
            fields=list(fields),
        )
