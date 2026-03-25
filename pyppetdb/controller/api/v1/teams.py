import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB

from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_authorities import CrudCAAuthorities

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.teams import filter_list
from pyppetdb.model.teams import filter_literal
from pyppetdb.model.teams import sort_literal
from pyppetdb.model.teams import TeamGet
from pyppetdb.model.teams import TeamGetMulti
from pyppetdb.model.teams import TeamPost
from pyppetdb.model.teams import TeamPut


class ControllerApiV1Teams:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes_groups: CrudNodesGroups,
        crud_teams: CrudTeams,
        crud_ldap: CrudLdap,
        crud_ca_spaces: CrudCASpaces,
        crud_ca_authorities: CrudCAAuthorities,
    ):
        self._authorize = authorize
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_teams = crud_teams
        self._crud_ldap = crud_ldap
        self._crud_ca_spaces = crud_ca_spaces
        self._crud_ca_authorities = crud_ca_authorities
        self._log = log

        self._router = APIRouter(
            prefix="/teams",
            tags=["teams"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=TeamGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{team_id}",
            self.create,
            response_model=TeamGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{team_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{team_id}",
            self.get,
            response_model=TeamGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{team_id}",
            self.update,
            response_model=TeamGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_nodes_groups(self):
        return self._crud_nodes_groups

    @property
    def crud_teams(self):
        return self._crud_teams

    @property
    def crud_ldap(self):
        return self._crud_ldap

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def _validate_permissions(self, permissions: list[str]):
        if not permissions:
            return

        import re
        from pyppetdb.errors import QueryParamValidationError, ResourceNotFound

        patterns = {
            r"^CA:SPACES:CREATE$": None,
            r"^CA:SPACES:UPDATE$": None,
            r"^CA:SPACES:DELETE$": None,
            r"^CA:AUTHORITIES:CREATE$": None,
            r"^CA:AUTHORITIES:UPDATE$": None,
            r"^CA:AUTHORITIES:DELETE$": None,
            r"^CA:SPACES:([^:]+):CERTS:UPDATE$": "space",
            r"^CA:AUTHORITIES:([^:]+):CERTS:UPDATE$": "authority",
        }

        for perm in permissions:
            matched = False
            for pattern, lookup_type in patterns.items():
                match = re.match(pattern, perm)
                if match:
                    matched = True
                    if lookup_type == "space":
                        resource_id = match.group(1)
                        try:
                            await self._crud_ca_spaces.get(resource_id, fields=["id"])
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"CA Space '{resource_id}' does not exist (referenced in permission '{perm}')"
                            )
                    elif lookup_type == "authority":
                        resource_id = match.group(1)
                        try:
                            await self._crud_ca_authorities.get(
                                resource_id, fields=["id"]
                            )
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"CA Authority '{resource_id}' does not exist (referenced in permission '{perm}')"
                            )
                    break

            if not matched:
                raise QueryParamValidationError(
                    msg=f"Invalid permission format: '{perm}'"
                )

    async def create(
        self,
        request: Request,
        data: TeamPost,
        team_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        if data.ldap_group:
            data.users = await self.crud_ldap.get_logins_from_group(
                group=data.ldap_group
            )

        await self._validate_permissions(data.permissions)

        return await self.crud_teams.create(
            _id=team_id,
            payload=data,
            fields=list(fields),
        )

    async def delete(
        self,
        request: Request,
        team_id: str,
    ):
        await self.authorize.require_admin(request=request)
        await self.crud_nodes_groups.delete_team_from_nodes_groups(team_id=team_id)
        return await self.crud_teams.delete(
            _id=team_id,
        )

    async def get(
        self,
        team_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_teams.get(_id=team_id, fields=list(fields))

    async def search(
        self,
        request: Request,
        team_id: str = Query(description="filter: regular_expressions", default=None),
        ldap_group: str = Query(
            description="filter: regular_expressions", default=None
        ),
        users: str = Query(description="filter: regular_expressions", default=None),
        permissions: str = Query(
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
        return await self.crud_teams.search(
            _id=team_id,
            ldap_group=ldap_group,
            users=users,
            permissions=permissions,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        data: TeamPut,
        team_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        current_group = await self.crud_teams.get(
            _id=team_id,
            fields=["ldap_group", "users", "permissions"],
        )
        if data.ldap_group:
            data.users = await self.crud_ldap.get_logins_from_group(
                group=data.ldap_group
            )
        elif current_group.ldap_group:
            data.users = await self.crud_ldap.get_logins_from_group(
                group=current_group.ldap_group
            )

        if data.permissions is not None:
            await self._validate_permissions(data.permissions)

        return await self.crud_teams.update(
            _id=team_id,
            payload=data,
            fields=list(fields),
        )
