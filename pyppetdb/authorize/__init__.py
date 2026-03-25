import logging
import typing

from fastapi import Request

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

    async def get_cert_info(self, request: Request) -> dict | None:
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
                cert = await self.crud_ca_certificates.get(
                    _id=serial, fields=["status", "cn"]
                )

                if cert.cn != cn:
                    self._log.error(
                        f"Access denied: CN mismatch. Cert: {cn}, DB: {cert.cn}"
                    )
                    raise ClientCertError(detail="Certificate CN mismatch")

                if cert.status != "signed":
                    self._log.warning(
                        f"Access denied: certificate for {cn} (serial {serial}) has status '{cert.status}'"
                    )
                    raise ClientCertError(detail=f"Certificate is {cert.status}")
            except ResourceNotFound:
                self._log.error(
                    f"Access denied: certificate for {cn} (serial {serial}) not found in database (unauthorized certificate)"
                )
                raise ClientCertError(detail="Certificate not found in database")

    async def require_cn(self, request: Request):
        cert = await self.get_cert_info(request)
        cn = cert["cn"]
        return cn

    async def require_cn_match(self, request: Request, match: str):
        cert = await self.get_cert_info(request)
        cn = cert["cn"]
        if cn != match:
            raise ClientCertError(detail=f"CN {cn} does not match {match}")
        return cn

    async def require_cn_trusted(self, request: Request) -> str:
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
        self, request: Request, permission: str, user=None
    ) -> UserGet:
        if not user:
            user = await self.get_user(request=request)
        if user.admin:
            return user

        teams = await self.crud_teams.search(
            users=f"^{user.id}$", permissions=f"^{permission}$", fields=["id"]
        )
        if teams.meta.result_size > 0:
            return user

        raise PermissionError(msg=f"Permission {permission} required")
