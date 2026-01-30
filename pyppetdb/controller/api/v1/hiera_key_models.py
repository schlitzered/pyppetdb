import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize
from pyppetdb.crud.hiera_key_models import CrudHieraKeyModels

from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models import filter_list
from pyppetdb.model.hiera_key_models import filter_literal
from pyppetdb.model.hiera_key_models import sort_literal
from pyppetdb.model.hiera_key_models import HieraKeyModelGet
from pyppetdb.model.hiera_key_models import HieraKeyModelGetMulti


class ControllerApiV1HieraKeyModels:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_key_models: CrudHieraKeyModels,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models = crud_hiera_key_models
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/key_models",
            tags=["hiera_key_models"],
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
    def crud_hiera_key_models(self):
        return self._crud_hiera_key_models

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
        return self.crud_hiera_key_models.search(
            _id=key_model_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def get(
        self,
        request: Request,
        key_model_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return self.crud_hiera_key_models.get(
            _id=key_model_id,
            fields=list(fields),
        )
