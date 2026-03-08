import logging
from typing import Set
from fastapi import APIRouter, Request, Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.model.ca_spaces import (
    CASpacePost, CASpaceGet, CASpaceGetMulti,
    filter_literal, filter_list, sort_literal
)
from pyppetdb.model.common import sort_order_literal

class ControllerApiV1CASpaces:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_spaces: CrudCASpaces,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_spaces = crud_spaces
        self._router = APIRouter(prefix="/ca/spaces", tags=["ca"])

        self._router.add_api_route(
            "",
            self.search_spaces,
            methods=["GET"],
            response_model=CASpaceGetMulti,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{space_id}",
            self.create_space,
            methods=["POST"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{space_id}",
            self.get_space,
            methods=["GET"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True
        )

    @property
    def router(self):
        return self._router

    async def create_space(
        self,
        request: Request,
        space_id: str,
        data: CASpacePost,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        data.id = space_id
        return await self._crud_spaces.create(payload=data, fields=list(fields))

    async def get_space(
        self,
        request: Request,
        space_id: str,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_spaces.get(_id=space_id, fields=list(fields))

    async def search_spaces(
        self,
        request: Request,
        space_id: str = Query(description="filter: regular_expressions", default=None),
        authority_id: str = Query(description="filter: regular_expressions", default=None),
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
        return await self._crud_spaces.search(
            _id=space_id,
            authority_id=authority_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
