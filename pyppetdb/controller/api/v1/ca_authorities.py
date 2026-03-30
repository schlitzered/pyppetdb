import logging
from typing import Set
from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.teams import CrudTeams
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
        crud_teams: CrudTeams,
        ca_service: CAService,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_authorities = crud_authorities
        self._crud_teams = crud_teams
        self._ca_service = ca_service
        self._router = APIRouter(prefix="/ca/authorities", tags=["ca authorities"])

        self._router.add_api_route(
            "",
            self.search,
            methods=["GET"],
            response_model=CAAuthorityGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.create,
            methods=["POST"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.get,
            methods=["GET"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.update,
            methods=["PUT"],
            response_model=CAAuthorityGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{ca_id}",
            self.delete,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

    async def update(
        self,
        request: Request,
        ca_id: str,
        data: CAAuthorityPut,
    ):
        await self._authorize.require_perm(
            request=request, permission="CA:AUTHORITIES:UPDATE"
        )
        if data.status == "revoked":
            return await self._ca_service.revoke_authority(ca_id)
        return None

    async def delete(
        self,
        request: Request,
        ca_id: str,
    ):
        await self._authorize.require_perm(
            request=request, permission="CA:AUTHORITIES:DELETE"
        )
        await self._ca_service.delete_authority(ca_id)
        await self._crud_teams.drop_permissions_by_pattern(f"^CA:AUTHORITIES:{ca_id}:")
        return {}

    async def create(
        self,
        request: Request,
        ca_id: str,
        data: CAAuthorityPost,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_perm(
            request=request, permission="CA:AUTHORITIES:CREATE"
        )
        return await self._ca_service.create_authority(_id=ca_id, payload=data)

    async def get(
        self,
        request: Request,
        ca_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_user(request=request)
        return await self._crud_authorities.get(_id=ca_id, fields=list(fields))

    async def search(
        self,
        request: Request,
        ca_id: str = Query(description="filter: regular_expressions", default=None),
        parent_id: str = Query(description="filter: regular_expressions", default=None),
        cn: str = Query(
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
        await self._authorize.require_user(request=request)
        return await self._crud_authorities.search(
            _id=ca_id,
            parent_id=parent_id,
            cn=cn,
            fingerprint=fingerprint,
            internal=internal,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
