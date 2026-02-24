import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_levels import filter_list
from pyppetdb.model.hiera_levels import filter_literal
from pyppetdb.model.hiera_levels import sort_literal
from pyppetdb.model.hiera_levels import HieraLevelGet
from pyppetdb.model.hiera_levels import HieraLevelGetMulti
from pyppetdb.model.hiera_levels import HieraLevelPost
from pyppetdb.model.hiera_levels import HieraLevelPut


class ControllerApiV1HieraLevels:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_hiera_levels: CrudHieraLevels,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_hiera_lookup_cache: CrudHieraLookupCache,
    ):
        self._authorize = authorize
        self._crud_hiera_levels = crud_hiera_levels
        self._crud_hiera_level_data = crud_hiera_level_data
        self._crud_hiera_lookup_cache = crud_hiera_lookup_cache
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/levels",
            tags=["hiera_levels"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=HieraLevelGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}",
            self.create,
            response_model=HieraLevelGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{level_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{level_id}",
            self.get,
            response_model=HieraLevelGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}",
            self.update,
            response_model=HieraLevelGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_hiera_levels(self):
        return self._crud_hiera_levels

    @property
    def crud_hiera_level_data(self):
        return self._crud_hiera_level_data

    @property
    def crud_hiera_lookup_cache(self):
        return self._crud_hiera_lookup_cache

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def create(
        self,
        request: Request,
        data: HieraLevelPost,
        level_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        result = await self.crud_hiera_levels.create(
            _id=level_id,
            payload=data,
            fields=list(fields),
        )
        if result.priority is not None:
            await self.crud_hiera_level_data.update_priority_by_level(
                level_id=level_id,
                priority=result.priority,
            )
        await self.crud_hiera_lookup_cache.clear_all()
        return result

    async def delete(
        self,
        request: Request,
        level_id: str,
    ):
        await self.authorize.require_admin(request=request)
        result = await self.crud_hiera_levels.delete(_id=level_id)
        await self.crud_hiera_lookup_cache.clear_all()
        return result

    async def get(
        self,
        level_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_levels.get(_id=level_id, fields=list(fields))

    async def search(
        self,
        request: Request,
        level_id: str = Query(description="filter: regular_expressions", default=None),
        priority: str = Query(default=None),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="priority"),
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
        return await self.crud_hiera_levels.search(
            _id=level_id,
            priority=priority,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        data: HieraLevelPut,
        level_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        result = await self.crud_hiera_levels.update(
            _id=level_id,
            payload=data,
            fields=list(fields),
        )
        if data.priority is not None:
            await self.crud_hiera_level_data.update_priority_by_level(
                level_id=level_id,
                priority=data.priority,
            )
        await self.crud_hiera_lookup_cache.clear_all()
        return result
