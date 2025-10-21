import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize

from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.ldap import CrudLdap

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
        authorize: Authorize,
        crud_nodes_groups: CrudNodesGroups,
        crud_teams: CrudTeams,
        crud_ldap: CrudLdap,
    ):
        self._authorize = authorize
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_teams = crud_teams
        self._crud_ldap = crud_ldap
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
            fields=["ldap_group", "users"],
        )
        if data.ldap_group:
            data.users = await self.crud_ldap.get_logins_from_group(
                group=data.ldap_group
            )
        elif current_group.ldap_group:
            data.users = await self.crud_ldap.get_logins_from_group(
                group=current_group.ldap_group
            )
        return await self.crud_teams.update(
            _id=team_id,
            payload=data,
            fields=list(fields),
        )
