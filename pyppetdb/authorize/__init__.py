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
import re
import typing

from fastapi import Request
from fastapi import WebSocket

from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.teams import CrudTeams

from pyppetdb.errors import AdminError
from pyppetdb.errors import ClientCertError
from pyppetdb.errors import CredentialError
from pyppetdb.errors import PermissionError
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import SessionCredentialError

from pyppetdb.model.users import UserGet


from pyppetdb.crud.ca_certificates import CrudCACertificates

# CA Permissions
PERM_CA_GET = "CA::GET"
PERM_CA_AUTHORITIES_CREATE = "CA:AUTHORITIES:CREATE"
PERM_CA_AUTHORITIES_UPDATE = "CA:AUTHORITIES:UPDATE"
PERM_CA_AUTHORITIES_DELETE = "CA:AUTHORITIES:DELETE"
PERM_CA_SPACES_CREATE = "CA:SPACES:CREATE"
PERM_CA_SPACES_UPDATE = "CA:SPACES:UPDATE"
PERM_CA_SPACES_DELETE = "CA:SPACES:DELETE"

# Hiera Permissions
PERM_HIERA_GET = "HIERA::GET"
PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE = "HIERA:KEY_MODELS_DYNAMIC::CREATE"
PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE = "HIERA:KEY_MODELS_DYNAMIC::DELETE"
PERM_HIERA_KEY_MODELS_CREATE = "HIERA:KEY_MODELS::CREATE"
PERM_HIERA_KEY_MODELS_UPDATE = "HIERA:KEY_MODELS::UPDATE"
PERM_HIERA_KEY_MODELS_DELETE = "HIERA:KEY_MODELS::DELETE"
PERM_HIERA_LEVELS_CREATE = "HIERA:LEVELS::CREATE"
PERM_HIERA_LEVELS_UPDATE = "HIERA:LEVELS::UPDATE"
PERM_HIERA_LEVELS_DELETE = "HIERA:LEVELS::DELETE"
PERM_HIERA_LEVEL_DATA_CREATE = "HIERA:LEVEL_DATA::CREATE"
PERM_HIERA_LEVEL_DATA_UPDATE = "HIERA:LEVEL_DATA::UPDATE"
PERM_HIERA_LEVEL_DATA_DELETE = "HIERA:LEVEL_DATA::DELETE"

# Jobs Permissions
PERM_JOBS_GET = "JOBS::GET"
PERM_JOBS_JOB_CREATE = "JOBS:JOB::CREATE"
PERM_JOBS_DEFINITION_CREATE = "JOBS:DEFINITION::CREATE"
PERM_JOBS_DEFINITION_UPDATE = "JOBS:DEFINITION::UPDATE"
PERM_JOBS_DEFINITION_DELETE = "JOBS:DEFINITION::DELETE"

# Nodes Permissions
PERM_NODES_CREATE = "NODES::CREATE"
PERM_NODES_UPDATE = "NODES::UPDATE"
PERM_NODES_DELETE = "NODES::DELETE"
PERM_NODES_CATALOG_CACHE_DELETE = "NODES:CATALOG_CACHE::DELETE"
PERM_NODES_GROUPS_CREATE = "NODES:GROUPS::CREATE"
PERM_NODES_GROUPS_UPDATE = "NODES:GROUPS::UPDATE"
PERM_NODES_GROUPS_DELETE = "NODES:GROUPS::DELETE"
PERM_NODES_GROUPS_GET = "NODES:GROUPS::GET"
PERM_NODES_SECRETS_REDACTOR_CREATE = "NODES:SECRETS_REDACTOR::CREATE"
PERM_NODES_SECRETS_REDACTOR_DELETE = "NODES:SECRETS_REDACTOR::DELETE"

# PyppetDB Nodes Permissions
PERM_PYPPETDB_NODES_GET = "PYPPETDB:NODES::GET"
PERM_PYPPETDB_NODES_DELETE = "PYPPETDB:NODES::DELETE"

# Teams Permissions
PERM_TEAMS_CREATE = "TEAMS::CREATE"
PERM_TEAMS_UPDATE = "TEAMS::UPDATE"
PERM_TEAMS_DELETE = "TEAMS::DELETE"
PERM_TEAMS_GET = "TEAMS::GET"

# Users Permissions
PERM_USERS_CREATE = "USERS::CREATE"
PERM_USERS_UPDATE = "USERS::UPDATE"
PERM_USERS_DELETE = "USERS::DELETE"
PERM_USERS_GET = "USERS::GET"
PERM_USERS_CREDENTIALS_CREATE = "USERS:CREDENTIALS::CREATE"
PERM_USERS_CREDENTIALS_UPDATE = "USERS:CREDENTIALS::UPDATE"
PERM_USERS_CREDENTIALS_DELETE = "USERS:CREDENTIALS::DELETE"
PERM_USERS_CREDENTIALS_GET = "USERS:CREDENTIALS::GET"

# Dynamic Permissions
PERM_CA_AUTHORITIES_CERTS_UPDATE = "CA:AUTHORITIES:{ca_id}:CERTS:UPDATE"
PERM_CA_SPACES_CERTS_UPDATE = "CA:SPACES:{space_id}:CERTS:UPDATE"
PERM_HIERA_LEVEL_DATA_CREATE_DYNAMIC = "HIERA:LEVEL_DATA:{key_id}:CREATE"
PERM_HIERA_LEVEL_DATA_DELETE_DYNAMIC = "HIERA:LEVEL_DATA:{key_id}:DELETE"
PERM_HIERA_LEVEL_DATA_UPDATE_DYNAMIC = "HIERA:LEVEL_DATA:{key_id}:UPDATE"
PERM_JOBS_JOB_CREATE_DYNAMIC = "JOBS:JOB:{definition_id}:CREATE"

# Permission Patterns
PATTERN_CA_AUTHORITIES = "^CA:AUTHORITIES:{ca_id}:"
PATTERN_CA_SPACES = "^CA:SPACES:{space_id}:"
PATTERN_HIERA_LEVEL_DATA = "^HIERA:LEVEL_DATA:{key_id}:"
PATTERN_JOBS_JOB = "^JOBS:JOB:{definition_id}:"


class AuthorizeClientCert:
    def __init__(
        self,
        log: logging.Logger,
        trusted_cns: list[str],
        crud_ca_certificates: typing.Optional[CrudCACertificates] = None,
    ):
        self._log = log
        self._trusted_cns = trusted_cns
        self._crud_ca_certificates = crud_ca_certificates

    @property
    def log(self):
        return self._log

    @property
    def crud_ca_certificates(self):
        return self._crud_ca_certificates

    async def get_cert_info(self, request: Request | WebSocket) -> dict | None:
        cert = request.scope.get("client_cert_dict")
        if not cert:
            raise ClientCertError(detail="No client certificate provided")
        self.log.debug(cert)
        subject = {key: value for rdn in cert.get("subject", []) for key, value in rdn}

        serial_hex = cert.get("serialNumber")
        if not serial_hex:
            raise ClientCertError(detail="Certificate serial number missing")

        try:
            serial_dec = str(int(serial_hex, 16))
        except ValueError:
            raise ClientCertError(detail="Invalid certificate serial number format")

        cert_info = {
            "cn": subject.get("commonName"),
            "serial": serial_dec,
        }
        await self._check_revocation(cert_info=cert_info)
        return cert_info

    async def _check_revocation(self, cert_info):
        cn = cert_info["cn"]
        serial = cert_info["serial"]
        if self.crud_ca_certificates:
            try:
                cert = await self.crud_ca_certificates.get_by_serial(
                    serial=serial, fields=["status", "cn"]
                )

                if cert.cn != cn:
                    self.log.error(
                        f"Access denied: CN mismatch. Cert: {cn}, DB: {cert.cn}"
                    )
                    raise ClientCertError(detail="Certificate CN mismatch")

                if cert.status != "signed":
                    self.log.warning(
                        f"Access denied: certificate for {cn} (serial {serial}) has status '{cert.status}'"
                    )
                    raise ClientCertError(detail=f"Certificate is {cert.status}")
            except ResourceNotFound:
                self.log.error(
                    f"Access denied: certificate for {cn} (serial {serial}) not found in database (unauthorized certificate)"
                )
                raise ClientCertError(detail="Certificate not found in database")

    async def require_cn(self, request: Request | WebSocket):
        cert = await self.get_cert_info(request)
        cn = cert["cn"]
        return cn

    async def require_cn_match(self, request: Request | WebSocket, match: str):
        cert = await self.get_cert_info(request)
        cn = cert["cn"]
        if cn != match:
            raise ClientCertError(detail=f"CN {cn} does not match {match}")
        return cn

    async def require_cn_trusted(self, request: Request | WebSocket) -> str:
        cert = await self.get_cert_info(request)
        cn = cert["cn"]
        if cn not in self._trusted_cns:
            raise ClientCertError(
                detail=f"CN {cn} is not in trustedCns {self._trusted_cns}"
            )
        return cn


class AuthorizePyppetDB:
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

    async def require_perm(
        self, request: Request, permission: str | list[str], user=None
    ) -> UserGet:
        if not user:
            user = await self.get_user(request=request)
        if user.admin:
            return user

        if isinstance(permission, str):
            permissions = [permission]
        else:
            permissions = permission

        perm_regex = "^(" + "|".join([re.escape(p) for p in permissions]) + ")$"

        teams = await self.crud_teams.search(
            users=f"^{user.id}$", permissions=perm_regex, fields=["id"]
        )
        if teams.meta.result_size > 0:
            return user

        raise PermissionError(msg=f"Permission {permission} required")
