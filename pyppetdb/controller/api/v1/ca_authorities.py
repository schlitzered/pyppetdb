import logging
from typing import Set
from fastapi import APIRouter, Request, Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.errors import QueryParamValidationError
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
        crud_spaces: CrudCASpaces,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
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
        self._router.add_api_route(
            "/{ca_id}",
            self.delete_authority,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True
        )

    @property
    def router(self):
        return self._router

    async def delete_authority(
        self,
        request: Request,
        ca_id: str,
    ):
        await self._authorize.require_admin(request=request)
        
        # Check if used by any space
        count = await self._crud_spaces.count({"authority_id": ca_id})
        if count > 0:
            raise QueryParamValidationError(msg=f"CA Authority '{ca_id}' is still in use by one or more spaces")

        # Check if it's a parent of another CA
        count = await self._crud_authorities.count({"parent_id": ca_id})
        if count > 0:
            raise QueryParamValidationError(msg=f"CA Authority '{ca_id}' is still a parent of one or more CA Authorities")

        await self._crud_authorities.delete(_id=ca_id)
        return {}

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
        fingerprint: str = Query(description="filter: regular_expressions", default=None),
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
            fingerprint=fingerprint,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
