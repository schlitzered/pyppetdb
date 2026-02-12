import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic

from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models_static import filter_list
from pyppetdb.model.hiera_key_models_static import filter_literal
from pyppetdb.model.hiera_key_models_static import sort_literal
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGet
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGetMulti
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_DYNAMIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_STATIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import split_key_model_id


class ControllerApiV1HieraKeyModelsStatic:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models_static = crud_hiera_key_models_static
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/key_models/static",
            tags=["hiera_key_models_static"],
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
    def crud_hiera_key_models_static(self):
        return self._crud_hiera_key_models_static

    @property
    def router(self):
        return self._router

    def _normalize_id(self, key_model_id: str) -> str:
        prefix, raw_id = split_key_model_id(key_model_id)
        if prefix != KEY_MODEL_STATIC_PREFIX:
            raise QueryParamValidationError(
                msg=f"invalid key model id {key_model_id}, expected static prefix"
            )
        return f"{KEY_MODEL_STATIC_PREFIX}{raw_id}"

    def _with_prefix(self, item: HieraKeyModelGet) -> HieraKeyModelGet:
        if item.id is None:
            return item
        prefix, raw_id = split_key_model_id(item.id)
        if prefix != KEY_MODEL_STATIC_PREFIX:
            return item
        return HieraKeyModelGet(
            id=f"{KEY_MODEL_STATIC_PREFIX}{raw_id}",
            description=item.description,
            model=item.model,
        )

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
        if key_model_id:
            if key_model_id.startswith(KEY_MODEL_STATIC_PREFIX):
                pass
            elif key_model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
                raise QueryParamValidationError(
                    msg=f"invalid key model id {key_model_id}, expected static prefix"
                )
            else:
                key_model_id = f"{KEY_MODEL_STATIC_PREFIX}{key_model_id}"
        result = self.crud_hiera_key_models_static.search(
            _id=key_model_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        filtered = []
        for item in result.result:
            if not item.id:
                continue
            if not item.id.startswith(KEY_MODEL_STATIC_PREFIX):
                continue
            filtered.append(self._with_prefix(item))
        result.result = filtered
        return result

    async def get(
        self,
        request: Request,
        key_model_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        raw_id = self._normalize_id(key_model_id)
        result = self.crud_hiera_key_models_static.get(
            _id=raw_id,
            fields=list(fields),
        )
        return self._with_prefix(result)
