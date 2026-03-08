import logging
from typing import Set
from fastapi import APIRouter, Request, Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost, CAAuthorityGet, CAAuthorityGetMulti,
    filter_literal, filter_list, sort_literal
)
from pyppetdb.model.common import sort_order_literal

class ControllerApiV1CAAuthorities:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_authorities: CrudCAAuthorities,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_authorities = crud_authorities
        self._router = APIRouter(prefix="/ca/authorities", tags=["ca"])

        self._router.add_api_route(
            "",
            self.search_authorities,
            methods=["GET"],
            response_model=CAAuthorityGetMulti,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.create_authority,
            methods=["POST"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.get_authority,
            methods=["GET"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True
        )

    @property
    def router(self):
        return self._router

    async def create_authority(
        self,
        request: Request,
        ca_id: str,
        data: CAAuthorityPost,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        data.id = ca_id
        return await self._crud_authorities.create(payload=data, fields=list(fields))

    async def get_authority(
        self,
        request: Request,
        ca_id: str,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_authorities.get(_id=ca_id, fields=list(fields))

    async def search_authorities(
        self,
        request: Request,
        ca_id: str = Query(description="filter: regular_expressions", default=None),
        parent_id: str = Query(description="filter: regular_expressions", default=None),
        common_name: str = Query(description="filter: regular_expressions", default=None),
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
        await self._authorize.require_admin(request=request)
        return await self._crud_authorities.search(
            _id=ca_id,
            parent_id=parent_id,
            common_name=common_name,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
