import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models_static import filter_list
from pyppetdb.model.hiera_key_models_static import filter_literal
from pyppetdb.model.hiera_key_models_static import sort_literal
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGet
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGetMulti
from pyppetdb.model.hiera_key_models_dynamic import HieraKeyModelDynamicPost
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX


class ControllerApiV1HieraKeyModelsDynamic:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_hiera_key_models_dynamic: CrudHieraKeyModelsDynamic,
        crud_hiera_keys: CrudHieraKeys,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models_dynamic = crud_hiera_key_models_dynamic
        self._crud_hiera_keys = crud_hiera_keys
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/key_models/dynamic",
            tags=["hiera_key_models_dynamic"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=HieraKeyModelGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{key_model_id}",
            self.create,
            response_model=HieraKeyModelGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{key_model_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{key_model_id}",
            self.get,
            response_model=HieraKeyModelGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def log(self):
        return self._log

    @property
    def crud_hiera_key_models_dynamic(self):
        return self._crud_hiera_key_models_dynamic

    @property
    def crud_hiera_keys(self):
        return self._crud_hiera_keys

    @property
    def router(self):
        return self._router

    async def search(
        self,
        request: Request,
        key_model_id: str = Query(
            description="filter: regular_expressions", default=None
        ),
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
        result = await self.crud_hiera_key_models_dynamic.search(
            _id=key_model_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return result

    async def get(
        self,
        request: Request,
        key_model_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        result = await self.crud_hiera_key_models_dynamic.get(
            _id=key_model_id,
            fields=list(fields),
        )
        return result

    async def create(
        self,
        request: Request,
        data: HieraKeyModelDynamicPost,
        key_model_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        if not key_model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
            raise QueryParamValidationError(
                msg=f"invalid key model id {key_model_id}, expected dynamic prefix"
            )
        result = await self.crud_hiera_key_models_dynamic.create(
            _id=key_model_id,
            payload=data,
            fields=list(fields),
        )
        return result

    async def delete(
        self,
        request: Request,
        key_model_id: str,
    ):
        await self.authorize.require_admin(request=request)
        keys = await self.crud_hiera_keys.search(
            model=key_model_id,
            fields=["id"],
            limit=10,
        )
        if keys.result:
            key_ids = [item.id for item in keys.result if item.id]
            raise QueryParamValidationError(
                msg=(
                    f"dynamic key model {key_model_id} is still in use, example keys: "
                    f"{', '.join(key_ids)}"
                )
            )
        await self.crud_hiera_key_models_dynamic.delete(_id=key_model_id)
        return DataDelete()
