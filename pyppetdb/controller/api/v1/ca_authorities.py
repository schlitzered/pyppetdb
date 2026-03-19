import logging
from typing import Set
from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CAAuthorityPut
from pyppetdb.model.ca_authorities import filter_literal
from pyppetdb.model.ca_authorities import filter_list
from pyppetdb.model.ca_authorities import sort_literal
from pyppetdb.model.common import sort_order_literal


class ControllerApiV1CAAuthorities:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_authorities: CrudCAAuthorities,
        ca_service: CAService,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_authorities = crud_authorities
        self._ca_service = ca_service
        self._router = APIRouter(prefix="/ca/authorities", tags=["ca authorities"])

        self._router.add_api_route(
            "",
            self.search_authorities,
            methods=["GET"],
            response_model=CAAuthorityGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.create_authority,
            methods=["POST"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.get_authority,
            methods=["GET"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.update_authority_status,
            methods=["PUT"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.delete_authority,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

    async def update_authority_status(
        self,
        request: Request,
        ca_id: str,
        data: CAAuthorityPut,
    ):
        await self._authorize.require_admin(request=request)
        if data.status == "revoked":
            return await self._ca_service.revoke_authority(ca_id)

    async def delete_authority(
        self,
        request: Request,
        ca_id: str,
    ):
        await self._authorize.require_admin(request=request)
        await self._ca_service.delete_authority(ca_id)
        return {}

    async def create_authority(
        self,
        request: Request,
        ca_id: str,
        data: CAAuthorityPost,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_authorities.create(
            _id=ca_id, payload=data, fields=list(fields)
        )

    async def get_authority(
        self,
        request: Request,
        ca_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_authorities.get(_id=ca_id, fields=list(fields))

    async def search_authorities(
        self,
        request: Request,
        ca_id: str = Query(description="filter: regular_expressions", default=None),
        parent_id: str = Query(description="filter: regular_expressions", default=None),
        common_name: str = Query(
            description="filter: regular_expressions", default=None
        ),
        fingerprint: str = Query(
            description="filter: regular_expressions", default=None
        ),
        internal: bool = Query(default=None),
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
            internal=internal,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
