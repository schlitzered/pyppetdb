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

from fastapi import APIRouter
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_TEAMS_GET
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_CA_AUTHORITIES_CREATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_UPDATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_DELETE
from pyppetdb.authorize import PERM_CA_SPACES_CREATE
from pyppetdb.authorize import PERM_CA_SPACES_UPDATE
from pyppetdb.authorize import PERM_CA_SPACES_DELETE
from pyppetdb.authorize import PERM_HIERA_GET
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE
from pyppetdb.authorize import PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE
from pyppetdb.authorize import PERM_HIERA_KEYS_CREATE
from pyppetdb.authorize import PERM_HIERA_KEYS_UPDATE
from pyppetdb.authorize import PERM_HIERA_KEYS_DELETE
from pyppetdb.authorize import PERM_HIERA_LEVELS_CREATE
from pyppetdb.authorize import PERM_HIERA_LEVELS_UPDATE
from pyppetdb.authorize import PERM_HIERA_LEVELS_DELETE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_CREATE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_UPDATE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_DELETE
from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.authorize import PERM_JOBS_JOB_CREATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_CREATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_UPDATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_DELETE
from pyppetdb.authorize import PERM_NODES_CREATE
from pyppetdb.authorize import PERM_NODES_UPDATE
from pyppetdb.authorize import PERM_NODES_DELETE
from pyppetdb.authorize import PERM_NODES_CATALOG_CACHE_DELETE
from pyppetdb.authorize import PERM_NODES_GROUPS_CREATE
from pyppetdb.authorize import PERM_NODES_GROUPS_UPDATE
from pyppetdb.authorize import PERM_NODES_GROUPS_DELETE
from pyppetdb.authorize import PERM_NODES_GROUPS_GET
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_CREATE
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_DELETE
from pyppetdb.authorize import PERM_PYPPETDB_NODES_GET
from pyppetdb.authorize import PERM_PYPPETDB_NODES_DELETE
from pyppetdb.authorize import PERM_TEAMS_CREATE
from pyppetdb.authorize import PERM_TEAMS_UPDATE
from pyppetdb.authorize import PERM_TEAMS_DELETE
from pyppetdb.authorize import PERM_USERS_CREATE
from pyppetdb.authorize import PERM_USERS_UPDATE
from pyppetdb.authorize import PERM_USERS_DELETE
from pyppetdb.authorize import PERM_USERS_GET
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_CREATE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_UPDATE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_DELETE
from pyppetdb.authorize import PERM_USERS_CREDENTIALS_GET
from pyppetdb.authorize import PERM_CA_AUTHORITIES_CERTS_UPDATE
from pyppetdb.authorize import PERM_CA_SPACES_CERTS_UPDATE
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_CREATE_DYNAMIC
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_UPDATE_DYNAMIC
from pyppetdb.authorize import PERM_HIERA_LEVEL_DATA_DELETE_DYNAMIC
from pyppetdb.authorize import PERM_JOBS_JOB_CREATE_DYNAMIC
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.model.permissions import PermissionsGet

STATIC_PERMISSIONS = sorted(
    [
        PERM_CA_GET,
        PERM_CA_AUTHORITIES_CREATE,
        PERM_CA_AUTHORITIES_UPDATE,
        PERM_CA_AUTHORITIES_DELETE,
        PERM_CA_SPACES_CREATE,
        PERM_CA_SPACES_UPDATE,
        PERM_CA_SPACES_DELETE,
        PERM_HIERA_GET,
        PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE,
        PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE,
        PERM_HIERA_KEYS_CREATE,
        PERM_HIERA_KEYS_UPDATE,
        PERM_HIERA_KEYS_DELETE,
        PERM_HIERA_LEVELS_CREATE,
        PERM_HIERA_LEVELS_UPDATE,
        PERM_HIERA_LEVELS_DELETE,
        PERM_HIERA_LEVEL_DATA_CREATE,
        PERM_HIERA_LEVEL_DATA_UPDATE,
        PERM_HIERA_LEVEL_DATA_DELETE,
        PERM_JOBS_GET,
        PERM_JOBS_JOB_CREATE,
        PERM_JOBS_DEFINITION_CREATE,
        PERM_JOBS_DEFINITION_UPDATE,
        PERM_JOBS_DEFINITION_DELETE,
        PERM_NODES_CREATE,
        PERM_NODES_UPDATE,
        PERM_NODES_DELETE,
        PERM_NODES_CATALOG_CACHE_DELETE,
        PERM_NODES_GROUPS_CREATE,
        PERM_NODES_GROUPS_UPDATE,
        PERM_NODES_GROUPS_DELETE,
        PERM_NODES_GROUPS_GET,
        PERM_NODES_SECRETS_REDACTOR_CREATE,
        PERM_NODES_SECRETS_REDACTOR_DELETE,
        PERM_PYPPETDB_NODES_GET,
        PERM_PYPPETDB_NODES_DELETE,
        PERM_TEAMS_CREATE,
        PERM_TEAMS_UPDATE,
        PERM_TEAMS_DELETE,
        PERM_TEAMS_GET,
        PERM_USERS_CREATE,
        PERM_USERS_UPDATE,
        PERM_USERS_DELETE,
        PERM_USERS_GET,
        PERM_USERS_CREDENTIALS_CREATE,
        PERM_USERS_CREDENTIALS_UPDATE,
        PERM_USERS_CREDENTIALS_DELETE,
        PERM_USERS_CREDENTIALS_GET,
    ]
)


class ControllerApiV1Permissions:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_ca_authorities: CrudCAAuthorities,
        crud_ca_spaces: CrudCASpaces,
        crud_hiera_keys: CrudHieraKeys,
        crud_jobs_definitions: CrudJobsDefinitions,
    ):
        self._authorize = authorize
        self._crud_ca_authorities = crud_ca_authorities
        self._crud_ca_spaces = crud_ca_spaces
        self._crud_hiera_keys = crud_hiera_keys
        self._crud_jobs_definitions = crud_jobs_definitions
        self._log = log
        self._router = APIRouter(
            prefix="/permissions",
            tags=["permissions"],
        )

        self.router.add_api_route(
            "",
            self.get,
            response_model=PermissionsGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def router(self):
        return self._router

    async def get(self, request: Request):
        await self.authorize.require_perm(
            request=request,
            permission=PERM_TEAMS_GET,
        )

        dynamic = []

        authorities = await self._crud_ca_authorities.search(
            fields=["id"],
            limit=1000,
        )
        for authority in authorities.result:
            dynamic.append(PERM_CA_AUTHORITIES_CERTS_UPDATE.format(ca_id=authority.id))

        spaces = await self._crud_ca_spaces.search(
            fields=["id"],
            limit=1000,
        )
        for space in spaces.result:
            dynamic.append(PERM_CA_SPACES_CERTS_UPDATE.format(space_id=space.id))

        keys = await self._crud_hiera_keys.search(
            fields=["id"],
            limit=1000,
        )
        for key in keys.result:
            dynamic.append(PERM_HIERA_LEVEL_DATA_CREATE_DYNAMIC.format(key_id=key.id))
            dynamic.append(PERM_HIERA_LEVEL_DATA_UPDATE_DYNAMIC.format(key_id=key.id))
            dynamic.append(PERM_HIERA_LEVEL_DATA_DELETE_DYNAMIC.format(key_id=key.id))

        definitions = await self._crud_jobs_definitions.search(
            fields=["id"],
            limit=1000,
        )
        for definition in definitions.result:
            dynamic.append(
                PERM_JOBS_JOB_CREATE_DYNAMIC.format(definition_id=definition.id)
            )

        dynamic.sort()

        return PermissionsGet(
            static=STATIC_PERMISSIONS,
            dynamic=dynamic,
        )
