import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize

from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_STATIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import split_key_model_id
from pyppetdb.pyhiera import PyHiera

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import filter_complex_search
from pyppetdb.model.hiera_level_data import filter_list
from pyppetdb.model.hiera_level_data import filter_literal
from pyppetdb.model.hiera_level_data import sort_literal
from pyppetdb.model.hiera_level_data import HieraLevelDataGet
from pyppetdb.model.hiera_level_data import HieraLevelDataGetMulti
from pyppetdb.model.hiera_level_data import HieraLevelDataPost
from pyppetdb.model.hiera_level_data import HieraLevelDataPut


class ControllerApiV1HieraLevelData:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
        crud_hiera_key_models_dynamic: CrudHieraKeyModelsDynamic,
        crud_hiera_keys: CrudHieraKeys,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_hiera_levels: CrudHieraLevels,
        crud_hiera_lookup_cache: CrudHieraLookupCache,
        pyhiera: PyHiera,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models_static = crud_hiera_key_models_static
        self._crud_hiera_key_models_dynamic = crud_hiera_key_models_dynamic
        self._crud_hiera_keys = crud_hiera_keys
        self._crud_hiera_level_data = crud_hiera_level_data
        self._crud_hiera_levels = crud_hiera_levels
        self._crud_hiera_lookup_cache = crud_hiera_lookup_cache
        self._pyhiera = pyhiera
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/data",
            tags=["hiera_level_data"],
        )

        self.router.add_api_route(
            "/",
            self.search,
            response_model=HieraLevelDataGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.create,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.get,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.update,
            response_model=HieraLevelDataGet,
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
    def crud_hiera_keys(self):
        return self._crud_hiera_keys

    @property
    def crud_hiera_level_data(self):
        return self._crud_hiera_level_data

    @property
    def crud_hiera_levels(self):
        return self._crud_hiera_levels

    @property
    def crud_hiera_key_models_dynamic(self):
        return self._crud_hiera_key_models_dynamic

    @property
    def crud_hiera_lookup_cache(self):
        return self._crud_hiera_lookup_cache

    @property
    def pyhiera(self):
        return self._pyhiera

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def _normalize_model_id(self, model_id: str) -> str:
        prefix, raw_id = split_key_model_id(model_id)
        if prefix == KEY_MODEL_DYNAMIC_PREFIX:
            await self.crud_hiera_key_models_dynamic.get(_id=model_id, fields=["id"])
            return model_id
        self.crud_hiera_key_models_static.get(_id=model_id, fields=["id"])
        return model_id

    async def _get_model_type(self, model_id: str):
        key_model_id = await self._normalize_model_id(model_id)
        model_type = self.pyhiera.hiera.key_models.get(key_model_id)
        if not model_type:
            raise QueryParamValidationError(msg=f"key model {key_model_id} not found")
        return model_type, key_model_id

    async def create(
        self,
        request: Request,
        data: HieraLevelDataPost,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        level = await self.crud_hiera_levels.get(_id=level_id, fields=["priority"])
        model_type, key_model_id = await self._get_model_type(key.key_model_id)
        try:
            model_type().validate(data.data)
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"invalid data for key model {key_model_id}: {err}"
            )
        result = await self.crud_hiera_level_data.create(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            priority=level.priority,
            fields=list(fields),
        )
        await self.crud_hiera_lookup_cache.delete_by_key_and_facts(
            key_id=key_id, facts=result.facts
        )
        return result

    async def delete(
        self,
        request: Request,
        level_id: str,
        data_id: str,
        key_id: str,
    ):
        await self.authorize.require_admin(request=request)
        existing = await self.crud_hiera_level_data.get(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fields=["facts"],
        )
        result = await self.crud_hiera_level_data.delete(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
        )
        await self.crud_hiera_lookup_cache.delete_by_key_and_facts(
            key_id=key_id, facts=existing.facts
        )
        return result

    async def get(
        self,
        request: Request,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        level_data = await self.crud_hiera_level_data.get(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fields=list(fields),
        )
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        await self.crud_hiera_levels.get(_id=level_id, fields=["id"])
        model_type, key_model_id = await self._get_model_type(key.key_model_id)
        try:
            model_type().validate(level_data.data)
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"invalid data for key model {key_model_id}: {err}"
            )
        return level_data

    async def search(
        self,
        request: Request,
        level_id: str = Query(description="filter: regular_expressions", default=None),
        key_id: str = Query(description="filter: regular_expressions", default=None),
        data_id: str = Query(description="filter: regular_expressions", default=None),
        fact: filter_complex_search = Query(default=None),
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
        return await self.crud_hiera_level_data.search(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fact=fact,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        request: Request,
        data: HieraLevelDataPut,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        await self.crud_hiera_levels.get(_id=level_id, fields=["id"])
        if data.data is not None:
            model_type, key_model_id = await self._get_model_type(key.key_model_id)
            try:
                model_type().validate(data.data)
            except ValueError as err:
                raise QueryParamValidationError(
                    msg=f"invalid data for key model {key_model_id}: {err}"
                )
        existing = await self.crud_hiera_level_data.get(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fields=["facts"],
        )
        result = await self.crud_hiera_level_data.update(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            fields=list(fields),
        )
        await self.crud_hiera_lookup_cache.delete_by_key_and_facts(
            key_id=key_id, facts=existing.facts
        )
        return result
