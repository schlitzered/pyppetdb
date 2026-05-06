# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_TEAMS_CREATE
from pyppetdb.authorize import PERM_TEAMS_DELETE
from pyppetdb.authorize import PERM_TEAMS_GET
from pyppetdb.authorize import PERM_TEAMS_UPDATE
from pyppetdb.authorize import PERM_CA_SPACES_CREATE
from pyppetdb.authorize import PERM_CA_SPACES_UPDATE
from pyppetdb.authorize import PERM_CA_SPACES_DELETE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_CREATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_UPDATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_DELETE
from pyppetdb.authorize import PERM_JOBS_JOB_CREATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_CREATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_UPDATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_DELETE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_CREATE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_UPDATE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_DELETE
from pyppetdb.authorize import PERM_HIERA_LEVELS_CREATE
from pyppetdb.authorize import PERM_HIERA_LEVELS_UPDATE
from pyppetdb.authorize import PERM_HIERA_LEVELS_DELETE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_CREATE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_UPDATE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_DELETE
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_CREATE
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_DELETE
from pyppetdb.authorize import PERM_NODES_CREATE
from pyppetdb.authorize import PERM_NODES_UPDATE
from pyppetdb.authorize import PERM_NODES_DELETE
from pyppetdb.authorize import PERM_NODES_CATALOG_CACHE_DELETE
from pyppetdb.authorize import PERM_NODES_GROUPS_CREATE
from pyppetdb.authorize import PERM_NODES_GROUPS_UPDATE
from pyppetdb.authorize import PERM_NODES_GROUPS_DELETE
from pyppetdb.authorize import PERM_NODES_GROUPS_GET
from pyppetdb.authorize import PERM_PYPPETDB_NODES_GET
from pyppetdb.authorize import PERM_PYPPETDB_NODES_DELETE
from pyppetdb.authorize import PERM_USERS_CREATE
from pyppetdb.authorize import PERM_USERS_UPDATE
from pyppetdb.authorize import PERM_USERS_DELETE
from pyppetdb.authorize import PERM_USERS_GET
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_CREATE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_UPDATE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_DELETE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_GET
from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_HIERA_GET
from pyppetdb.authorize import PATTERN_CA_SPACES
from pyppetdb.authorize import PATTERN_CA_AUTHORITIES
from pyppetdb.authorize import PATTERN_JOBS_JOB
from pyppetdb.authorize import PATTERN_HIERA_LEVEL_DATA


from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.teams import filter_list
from pyppetdb.model.teams import filter_literal
from pyppetdb.model.teams import sort_literal
from pyppetdb.model.teams import TeamGet
from pyppetdb.model.teams import TeamGetMulti
from pyppetdb.model.teams import TeamPost
from pyppetdb.model.teams import TeamPut
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions


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
        crud_jobs_definitions: CrudJobsDefinitions,
        crud_hiera_keys: CrudHieraKeys,
    ):
        self._authorize = authorize
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_teams = crud_teams
        self._crud_ldap = crud_ldap
        self._crud_ca_spaces = crud_ca_spaces
        self._crud_ca_authorities = crud_ca_authorities
        self._crud_jobs_definitions = crud_jobs_definitions
        self._crud_hiera_keys = crud_hiera_keys
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
            rf"^{PERM_CA_SPACES_CREATE}$": None,
            rf"^{PERM_CA_SPACES_UPDATE}$": None,
            rf"^{PERM_CA_SPACES_DELETE}$": None,
            rf"^{PERM_CA_AUTHORITIES_CREATE}$": None,
            rf"^{PERM_CA_AUTHORITIES_UPDATE}$": None,
            rf"^{PERM_CA_AUTHORITIES_DELETE}$": None,
            rf"^{PATTERN_CA_SPACES.replace('{space_id}', '([^:]+)')}CERTS:UPDATE$": "space",
            rf"^{PATTERN_CA_AUTHORITIES.replace('{ca_id}', '([^:]+)')}CERTS:UPDATE$": "authority",
            rf"^{PERM_JOBS_JOB_CREATE}$": None,
            rf"^{PATTERN_JOBS_JOB.replace('{definition_id}', '([^:]+)')}CREATE$": "job_definition",
            rf"^{PERM_JOBS_DEFINITION_CREATE}$": None,
            rf"^{PERM_JOBS_DEFINITION_UPDATE}$": None,
            rf"^{PERM_JOBS_DEFINITION_DELETE}$": None,
            rf"^{PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE}$": None,
            rf"^{PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE}$": None,
            rf"^{PERM_HIERA_KEY_MODELS_CREATE}$": None,
            rf"^{PERM_HIERA_KEY_MODELS_UPDATE}$": None,
            rf"^{PERM_HIERA_KEY_MODELS_DELETE}$": None,
            rf"^{PERM_HIERA_LEVELS_CREATE}$": None,
            rf"^{PERM_HIERA_LEVELS_UPDATE}$": None,
            rf"^{PERM_HIERA_LEVELS_DELETE}$": None,
            rf"^{PERM_HIERA_LEVEL_DATA_CREATE}$": None,
            rf"^{PERM_HIERA_LEVEL_DATA_UPDATE}$": None,
            rf"^{PERM_HIERA_LEVEL_DATA_DELETE}$": None,
            rf"^{PATTERN_HIERA_LEVEL_DATA.replace('{key_id}', '([^:]+)')}CREATE$": "hiera_key",
            rf"^{PATTERN_HIERA_LEVEL_DATA.replace('{key_id}', '([^:]+)')}UPDATE$": "hiera_key",
            rf"^{PATTERN_HIERA_LEVEL_DATA.replace('{key_id}', '([^:]+)')}DELETE$": "hiera_key",
            rf"^{PERM_NODES_SECRETS_REDACTOR_CREATE}$": None,
            rf"^{PERM_NODES_SECRETS_REDACTOR_DELETE}$": None,
            rf"^{PERM_NODES_CREATE}$": None,
            rf"^{PERM_NODES_UPDATE}$": None,
            rf"^{PERM_NODES_DELETE}$": None,
            rf"^{PERM_NODES_CATALOG_CACHE_DELETE}$": None,
            rf"^{PERM_NODES_GROUPS_CREATE}$": None,
            rf"^{PERM_NODES_GROUPS_UPDATE}$": None,
            rf"^{PERM_NODES_GROUPS_DELETE}$": None,
            rf"^{PERM_NODES_GROUPS_GET}$": None,
            rf"^{PERM_PYPPETDB_NODES_GET}$": None,
            rf"^{PERM_PYPPETDB_NODES_DELETE}$": None,
            rf"^{PERM_TEAMS_CREATE}$": None,
            rf"^{PERM_TEAMS_UPDATE}$": None,
            rf"^{PERM_TEAMS_DELETE}$": None,
            rf"^{PERM_TEAMS_GET}$": None,
            rf"^{PERM_USERS_CREATE}$": None,
            rf"^{PERM_USERS_UPDATE}$": None,
            rf"^{PERM_USERS_DELETE}$": None,
            rf"^{PERM_USERS_GET}$": None,
            rf"^{PERM_USERS_CREDENTIALS_CREATE}$": None,
            rf"^{PERM_USERS_CREDENTIALS_UPDATE}$": None,
            rf"^{PERM_USERS_CREDENTIALS_DELETE}$": None,
            rf"^{PERM_USERS_CREDENTIALS_GET}$": None,
            rf"^{PERM_JOBS_GET}$": None,
            rf"^{PERM_CA_GET}$": None,
            rf"^{PERM_HIERA_GET}$": None,
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
                            await self._crud_ca_spaces.resource_exists(resource_id)
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"CA Space '{resource_id}' does not exist (referenced in permission '{perm}')"
                            )
                    elif lookup_type == "authority":
                        resource_id = match.group(1)
                        try:
                            await self._crud_ca_authorities.resource_exists(resource_id)
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"CA Authority '{resource_id}' does not exist (referenced in permission '{perm}')"
                            )
                    elif lookup_type == "job_definition":
                        resource_id = match.group(1)
                        try:
                            await self._crud_jobs_definitions.resource_exists(
                                resource_id
                            )
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"Job Definition '{resource_id}' does not exist (referenced in permission '{perm}')"
                            )
                    elif lookup_type == "hiera_key":
                        resource_id = match.group(1)
                        try:
                            await self._crud_hiera_keys.resource_exists(resource_id)
                        except ResourceNotFound:
                            raise QueryParamValidationError(
                                msg=f"Hiera Key '{resource_id}' does not exist (referenced in permission '{perm}')"
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
        await self.authorize.require_perm(request=request, permission=PERM_TEAMS_CREATE)
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
        await self.authorize.require_perm(request=request, permission=PERM_TEAMS_DELETE)
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
        await self.authorize.require_perm(request=request, permission=PERM_TEAMS_GET)

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
        await self.authorize.require_perm(request=request, permission=PERM_TEAMS_GET)
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
        await self.authorize.require_perm(request=request, permission=PERM_TEAMS_UPDATE)
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
