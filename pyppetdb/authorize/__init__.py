import logging
import typing

from fastapi import Request

from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.teams import CrudTeams

from pyppetdb.errors import AdminError
from pyppetdb.errors import CredentialError
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import SessionCredentialError

from pyppetdb.model.users import UserGet


class Authorize:
    def __init__(
        self,
        log: logging.Logger,
        crud_node_groups: CrudNodesGroups,
        crud_teams: CrudTeams,
        crud_users: CrudUsers,
        crud_users_credentials: CrudCredentials,
    ):
        self._crud_node_groups = crud_node_groups
        self._crud_teams = crud_teams
        self._crud_users = crud_users
        self._crud_users_credentials = crud_users_credentials
        self._log = log

    @property
    def crud_node_groups(self):
        return self._crud_node_groups

    @property
    def crud_teams(self) -> CrudTeams:
        return self._crud_teams

    @property
    def crud_users(self) -> CrudUsers:
        return self._crud_users

    @property
    def crud_users_credentials(self):
        return self._crud_users_credentials

    @property
    def log(self):
        return self._log

    async def get_user(self, request: Request) -> UserGet:
        user = self.get_user_from_session(request=request)
        if not user:
            user = await self.get_user_from_credentials(request=request)
        if not user:
            raise SessionCredentialError
        user = await self.crud_users.get(_id=user, fields=["id", "admin"])
        return user

    async def get_user_from_credentials(self, request: Request) -> UserGet | None:
        try:
            user = await self.crud_users_credentials.check_credential(request=request)
            return user
        except (CredentialError, ResourceNotFound):
            return None

    @staticmethod
    def get_user_from_session(request: Request) -> typing.Optional[str]:
        return request.session.get("username", None)

    async def get_user_node_groups(self, request, user=None):
        if not user:
            user = await self.get_user(request=request)
        if user.admin:
            return None
        _teams = list()
        teams = await self.crud_teams.search(users=f"^{user.id}$", fields=["id"])
        for team in teams.result:
            _teams.append(team.id)
        _node_groups = list()
        node_groups = await self.crud_node_groups.search(
            teams_list=_teams, fields=["id"]
        )
        for node_group in node_groups.result:
            _node_groups.append(node_group.id)
        return _node_groups

    async def require_admin(self, request, user=None) -> UserGet:
        if not user:
            user = await self.get_user(request=request)
        if not user.admin:
            raise AdminError
        return user

    async def require_user(self, request) -> UserGet:
        user = await self.get_user(request)
        return user
