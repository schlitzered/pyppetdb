import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize

from pyppetdb.crud.hiera_level_data import CrudHieraLevelData

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
        crud_hiera_level_data: CrudHieraLevelData,
    ):
        self._authorize = authorize
        self._crud_hiera_level_data = crud_hiera_level_data
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
            "/{level_id}/{_id}/{key_id}",
            self.create,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{level_id}/{_id}/{key_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{level_id}/{_id}/{key_id}",
            self.get,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}/{_id}/{key_id}",
            self.update,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_hiera_level_data(self):
        return self._crud_hiera_level_data

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def create(
        self,
        request: Request,
        data: HieraLevelDataPost,
        level_id: str,
        _id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_level_data.create(
            _id=_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            fields=list(fields),
        )

    async def delete(
        self,
        request: Request,
        level_id: str,
        _id: str,
        key_id: str,
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_level_data.delete(
            _id=_id,
            key_id=key_id,
            level_id=level_id,
        )

    async def get(
        self,
        request: Request,
        level_id: str,
        _id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_level_data.get(
            _id=_id,
            key_id=key_id,
            level_id=level_id,
            fields=list(fields),
        )

    async def search(
        self,
        request: Request,
        level_id: str = Query(description="filter: regular_expressions", default=None),
        key_id: str = Query(description="filter: regular_expressions", default=None),
        _id: str = Query(description="filter: regular_expressions", default=None),
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
            _id=_id,
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
        _id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_level_data.update(
            _id=_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            fields=list(fields),
        )
