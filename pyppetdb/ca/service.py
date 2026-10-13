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

import asyncio
import datetime
import functools
import logging
import re
import typing
import uuid
from concurrent.futures import Executor

from pyppetdb.ca import crypto
from pyppetdb.ca.policy import injected_sans
from pyppetdb.ca.policy import signing_policy
from pyppetdb.ca.signer import CASigners
from pyppetdb.ca.validation import CSRValidator
from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_authorities import CACRL
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_authorities import CAAuthorityPostInternal
from pyppetdb.model.ca_authorities import CAAuthorityPut
from pyppetdb.model.ca_authorities import CAAuthorityPutInternal
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_certificates import CACertificatePostInternal
from pyppetdb.model.ca_certificates import CACertificatePut
from pyppetdb.model.ca_certificates import CACertificatePutInternal
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpacePostInternal
from pyppetdb.model.ca_spaces import CASpacePut
from pyppetdb.model.ca_spaces import CASpacePutInternal
from pyppetdb.model.ca_validation import CAValidationConfig


class CAService:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        signers: CASigners,
        validator: CSRValidator,
        executor: Executor,
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._signers = signers
        self._validator = validator
        self._executor = executor
        self._revocation_listeners = []

    @property
    def signers(self) -> CASigners:
        return self._signers

    @property
    def validator(self) -> CSRValidator:
        return self._validator

    async def _run(self, func, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, functools.partial(func, *args, **kwargs)
        )

    async def _sign(
        self,
        cn: str,
        ca: CAAuthorityGet,
        space: CASpaceGet,
        csr_pem: typing.Optional[bytes] = None,
        old_cert_pem: typing.Optional[bytes] = None,
        requested_sans: typing.Optional[list[str]] = None,
    ) -> bytes:
        signer = await self._signers.get(str(space.ca_id))
        policy = signing_policy(
            self.log, cn, ca.validation_config, space.validation_config
        )
        common = {
            "ca_cert": signer.certificate,
            "ca_key": signer.private_key,
            "key_usages": policy.key_usages,
            "extended_key_usages": policy.extended_key_usages,
            "validity_days": self._config.ca.certificateValidityDays,
            "allowed_extensions": policy.allowed_extensions,
            "injected_sans": policy.injected_sans,
        }
        if csr_pem:
            try:
                return await self._run(
                    crypto.sign_csr,
                    csr_pem,
                    honor_csr_sans=policy.honor_requested_sans,
                    **common,
                )
            except ValueError as err:
                raise QueryParamValidationError(msg=f"Failed to sign CSR: {err}")
        if old_cert_pem:
            try:
                return await self._run(
                    crypto.renew_cert,
                    old_cert_pem,
                    honor_cert_sans=policy.honor_requested_sans,
                    requested_sans=requested_sans,
                    **common,
                )
            except ValueError as err:
                raise QueryParamValidationError(
                    msg=f"Failed to renew certificate: {err}"
                )
        raise ValueError("Either csr_pem or old_cert_pem must be provided")

    async def create_authority(
        self, _id: str, payload: CAAuthorityPost, fields: list
    ) -> CAAuthorityGet:
        if payload.certificate and payload.private_key:
            return await self.import_authority(
                _id=_id,
                certificate_pem=payload.certificate.encode(),
                private_key_pem=payload.private_key.encode(),
                internal=False,
                fields=fields,
                cn=payload.cn,
                chain=payload.external_chain or [],
                validation_config=payload.validation_config,
            )
        subject = {
            "cn": payload.cn,
            "organization": str(payload.organization),
            "organizational_unit": str(payload.organizational_unit),
            "country": str(payload.country),
            "state": payload.state,
            "locality": payload.locality,
            "validity_days": int(payload.validity_days or 0),
        }
        chain: list[str] = []
        if payload.parent_id:
            parent = await self._get_signing_authority(payload.parent_id)
            signer = await self._signers.get(payload.parent_id)
            cert_pem, key_pem = await self._run(
                crypto.generate_ca,
                issuer_cert=signer.certificate,
                issuer_key=signer.private_key,
                **subject,
            )
            chain = [parent.certificate] + (parent.chain or [])
        else:
            cert_pem, key_pem = await self._run(crypto.generate_ca, **subject)
        return await self._store_authority(
            _id=_id,
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            internal=True,
            fields=fields,
            cn=payload.cn,
            parent_id=payload.parent_id,
            chain=chain,
            validation_config=payload.validation_config,
        )

    async def import_authority(
        self,
        _id: str,
        certificate_pem: bytes,
        private_key_pem: bytes,
        internal: bool,
        fields: list,
        cn: typing.Optional[str] = None,
        chain: typing.Optional[list[str]] = None,
        validation_config: typing.Optional[CAValidationConfig] = None,
    ) -> CAAuthorityGet:
        try:
            matches = await self._run(
                crypto.key_matches_certificate, certificate_pem, private_key_pem
            )
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"Invalid CA certificate or private key: {err}"
            )
        if not matches:
            raise QueryParamValidationError(
                msg="The private key does not belong to the CA certificate"
            )
        return await self._store_authority(
            _id=_id,
            certificate_pem=certificate_pem,
            private_key_pem=private_key_pem,
            internal=internal,
            fields=fields,
            cn=cn,
            chain=chain or [],
            validation_config=validation_config,
        )

    async def _store_authority(
        self,
        _id: str,
        certificate_pem: bytes,
        private_key_pem: bytes,
        internal: bool,
        fields: list,
        cn: typing.Optional[str],
        chain: list[str],
        validation_config: typing.Optional[CAValidationConfig],
        parent_id: typing.Optional[str] = None,
    ) -> CAAuthorityGet:
        info = await self._run(crypto.get_cert_info, certificate_pem)
        data = {
            "id": _id,
            "parent_id": parent_id,
            "cn": cn or info["cn"],
            "issuer": info["issuer"],
            "serial_number": info["serial_number"],
            "not_before": info["not_before"],
            "not_after": info["not_after"],
            "fingerprint": info["fingerprint"],
            "certificate": certificate_pem.decode(),
            "private_key_encrypted": self._crud_authorities.protector.encrypt_string(
                private_key_pem.decode()
            ),
            "internal": internal,
            "chain": chain,
            "status": "active",
            "validation_config": (
                validation_config or CAValidationConfig()
            ).model_dump(),
        }
        if internal:
            crl_pem, next_update = await self._run(
                crypto.generate_crl,
                certificate_pem,
                private_key_pem,
                [],
                self.config.ca.crlValidityDays,
            )
            data["crl"] = CACRL(
                crl_pem=crl_pem.decode(),
                generation=1,
                updated_at=datetime.datetime.now(datetime.timezone.utc),
                next_update=next_update,
            ).model_dump()
        return await self._crud_authorities.create(
            _id=_id, payload=CAAuthorityPostInternal(**data), fields=fields
        )

    async def _authority_path(self, ca_id: str) -> list[CAAuthorityGet]:
        path: list[CAAuthorityGet] = []
        seen: set[str] = set()
        current: typing.Optional[str] = ca_id
        while current:
            if current in seen:
                self.log.error(
                    f"CA Authority chain of '{ca_id}' contains a cycle at '{current}'"
                )
                raise QueryParamValidationError(
                    msg=f"CA Authority chain of '{ca_id}' contains a cycle"
                )
            seen.add(current)
            authority = await self._crud_authorities.get(
                current, fields=[], use_cache=True
            )
            path.append(authority)
            current = str(authority.parent_id) if authority.parent_id else None
        return path

    async def get_crl_chain(self, space_id: str) -> bytes:
        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        crl_chain_pem = b""
        for authority in await self._authority_path(str(space.ca_id)):
            if not authority.internal:
                self.log.debug(f"Skipping external CA '{authority.id}' in CRL chain")
                continue
            if not authority.crl:
                self.log.error(f"Internal CA '{authority.id}' is missing CRL data")
                continue
            crl_chain_pem += authority.crl.crl_pem.encode()
        return crl_chain_pem

    async def get_certificate_chain(self, space_id: str) -> bytes:
        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        return b"".join(
            authority.certificate.encode()
            for authority in await self._authority_path(str(space.ca_id))
            if authority.certificate
        )

    def add_revocation_listener(self, callback) -> None:
        self._revocation_listeners.append(callback)

    def _notify_revocation(self, serial: str) -> None:
        for callback in self._revocation_listeners:
            try:
                callback(serial)
            except Exception as e:
                self.log.error(f"Revocation listener failed for serial '{serial}': {e}")

    @property
    def log(self):
        return self._log

    @property
    def config(self):
        return self._config

    @staticmethod
    def _clean_pem(data: str | bytes) -> bytes:
        if not data:
            return b""
        if isinstance(data, str):
            data = data.encode()
        m = re.search(rb"-----BEGIN [^-]+-----.*?-----END [^-]+-----", data, re.DOTALL)
        if m:
            return m.group(0).strip()
        return data.strip()

    async def submit_certificate_request(
        self, space_id: str, csr_pem: str, fields: list, cn: str
    ) -> CACertificateGet:
        try:
            cleaned_csr = self._clean_pem(csr_pem)
            csr, csr_info = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                crypto.parse_and_extract_csr,
                cleaned_csr,
            )
        except Exception as e:
            raise QueryParamValidationError(msg=f"Invalid CSR: {e}")

        csr_cn = csr_info["cn"]

        if cn and cn != csr_cn:
            raise QueryParamValidationError(
                msg=f"CSR CN '{csr_cn}' does not match nodename '{cn}'"
            )

        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        ca = await self._crud_authorities.get(
            str(space.ca_id), fields=[], use_cache=True
        )

        await self._validator.validate(
            csr=csr,
            cn=csr_cn,
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_id=str(ca.id),
            space_id=space_id,
            secret_refs=[*ca.secret_refs, *space.secret_refs],
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "ca_id": str(space.ca_id),
            "cn": csr_cn,
            "space_id": space_id,
            "csr": cleaned_csr.decode(),
            "created": now,
            "request_expires": now
            + datetime.timedelta(days=self._config.ca.certificateRequestTtlDays),
            **csr_info,
            "requested_sans": crypto.csr_dns_sans(csr),
        }

        set_on_insert = {
            "id": str(uuid.uuid4().int),
            "cert_uniqueness": f"{space_id}:{csr_cn}",
        }

        try:
            return await self._crud_certificates.upsert_request(
                space_id=space_id,
                cn=csr_cn,
                payload=CACertificatePutInternal(**payload),
                fields=fields,
                set_on_insert=set_on_insert,
            )
        except DuplicateResource:
            raise DuplicateResource(
                msg=f"A signed certificate already exists for '{csr_cn}' in space '{space_id}'"
            )

    async def sign_certificate(
        self, space_id: str, cn: str, fields: list
    ) -> CACertificateGet:
        try:
            cert_req = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="requested", fields=["id"]
            )
            return await self.process_requested_certificate(str(cert_req.id))
        except ResourceNotFound:
            return await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="signed", fields=fields
            )

    async def process_requested_certificate(self, _id: str) -> CACertificateGet:
        cert_req = await self._crud_certificates.get(_id, fields=[])
        if cert_req.status != "requested":
            if cert_req.status == "signed":
                return cert_req
            raise QueryParamValidationError(
                msg=f"Certificate '{_id}' is in status '{cert_req.status}', expected 'requested'"
            )

        space = await self._crud_spaces.get(
            str(cert_req.space_id), fields=[], use_cache=True
        )
        ca = await self._get_signing_authority(str(space.ca_id))

        cert_pem = await self._sign(
            cn=str(cert_req.cn),
            ca=ca,
            space=space,
            csr_pem=self._clean_pem(str(cert_req.csr)),
        )

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            crypto.get_cert_info,
            cert_pem,
        )

        update_data = {
            "id": info["serial_number"],
            "certificate": cert_pem.decode(),
            "status": "signed",
            **info,
        }

        try:
            return await self._crud_certificates.update(
                _id=_id,
                payload=CACertificatePutInternal(**update_data),
                fields=[],
                unset=["request_expires"],
            )
        except DuplicateResource:
            return await self._crud_certificates.get(info["serial_number"], fields=[])

    async def revoke_certificate(self, _id: str) -> CACertificateGet:
        now = datetime.datetime.now(datetime.timezone.utc)
        request = await self._crud_certificates.delete_request(_id=_id)
        if request is not None:
            return request.model_copy(
                update={"status": "revoked", "revocation_date": now}
            )
        try:
            result = await self._crud_certificates.revoke(
                _id=_id, revocation_date=now, fields=[]
            )
        except ResourceNotFound:
            result = await self._crud_certificates.get(_id, fields=[])
        self._notify_revocation(_id)
        return result

    async def renew_certificate(self, space_id: str, cn: str) -> CACertificateGet:
        try:
            old_cert = await self._crud_certificates.get_by_cn(
                space_id=space_id,
                cn=cn,
                fields=[
                    "id",
                    "certificate",
                    "csr",
                    "requested_sans",
                    "status",
                ],
                status="signed",
            )
        except ResourceNotFound:
            raise ResourceNotFound(
                details=f"Certificate for {cn} in space {space_id} not found"
            )

        if not old_cert.certificate:
            raise QueryParamValidationError(
                msg=f"No signed certificate data found for {cn}, cannot renew"
            )

        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        ca = await self._get_signing_authority(str(space.ca_id))
        old_cert_pem = self._clean_pem(old_cert.certificate)
        requested_sans = await self._requested_sans(cn, ca, space, old_cert)
        await self._validator.validate_names(
            cn=cn,
            sans=requested_sans,
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_id=str(ca.id),
            space_id=space_id,
            secret_refs=[*ca.secret_refs, *space.secret_refs],
        )

        cert_pem = await self._sign(
            cn=cn,
            ca=ca,
            space=space,
            old_cert_pem=old_cert_pem,
            requested_sans=requested_sans,
        )

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            crypto.get_cert_info,
            cert_pem,
        )

        if old_cert.status == "signed":
            await self.revoke_certificate(str(old_cert.id))
        else:
            await self._crud_certificates.update(
                _id=str(old_cert.id),
                payload=CACertificatePutInternal(
                    cert_uniqueness=f"revoked:{old_cert.id}"
                ),
                fields=[],
            )

        new_cert_data = {
            "id": info["serial_number"],
            "ca_id": space.ca_id,
            "space_id": space_id,
            "cn": cn,
            "status": "signed",
            "certificate": cert_pem.decode(),
            "cert_uniqueness": f"{space_id}:{cn}",
            "csr": old_cert.csr,
            "created": datetime.datetime.now(datetime.timezone.utc),
            **info,
            "requested_sans": requested_sans,
        }

        return await self._crud_certificates.create(
            _id=info["serial_number"],
            payload=CACertificatePostInternal(**new_cert_data),
            fields=[],
        )

    async def import_certificate(
        self, space_id: str, certificate_pem: bytes, fields: list
    ) -> CACertificateGet:
        space = await self._crud_spaces.get(space_id, fields=[], use_cache=False)
        authority = await self._crud_authorities.get(
            str(space.ca_id), fields=[], use_cache=False
        )
        try:
            info = await self._run(crypto.get_cert_info, certificate_pem)
            issued = await self._run(
                crypto.issued_by, certificate_pem, authority.certificate.encode()
            )
            sans = await self._run(crypto.certificate_dns_sans, certificate_pem)
        except ValueError as err:
            raise QueryParamValidationError(msg=f"Invalid certificate: {err}")
        cn = info["cn"]
        if not issued:
            raise QueryParamValidationError(
                msg=f"Certificate for '{cn}' was not issued by CA Authority '{space.ca_id}'"
            )
        if info["not_after"] <= datetime.datetime.now(datetime.timezone.utc):
            raise QueryParamValidationError(
                msg=f"Certificate for '{cn}' expired on {info['not_after'].isoformat()}"
            )
        data = {
            "id": info["serial_number"],
            "ca_id": str(space.ca_id),
            "space_id": space_id,
            "cn": cn,
            "status": "signed",
            "certificate": certificate_pem.decode(),
            "cert_uniqueness": f"{space_id}:{cn}",
            "created": info["not_before"],
            **info,
            "requested_sans": [san for san in sans if san != cn],
        }
        return await self._crud_certificates.create(
            _id=info["serial_number"],
            payload=CACertificatePostInternal(**data),
            fields=fields,
        )

    async def _require_assignable_authority(self, ca_id: str) -> None:
        authority = await self._crud_authorities.get(ca_id, fields=[], use_cache=True)
        if authority.status == "revoked":
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' is revoked and cannot be assigned to a space"
            )

    async def create_space(
        self, _id: str, payload: CASpacePost, fields: list
    ) -> CASpaceGet:
        await self._require_assignable_authority(payload.ca_id)
        return await self._crud_spaces.create(
            _id=_id,
            payload=CASpacePostInternal(**payload.model_dump()),
            fields=fields,
        )

    async def update_space(
        self, _id: str, payload: CASpacePut, fields: list
    ) -> CASpaceGet:
        data_internal = payload.model_dump(exclude_unset=True)
        if payload.ca_id:
            await self._require_assignable_authority(payload.ca_id)
            current = await self._crud_spaces.get(
                _id, fields=["ca_id", "ca_id_history"], use_cache=False
            )
            if current.ca_id != payload.ca_id:
                history = current.ca_id_history or []
                if current.ca_id not in history:
                    history.append(str(current.ca_id))
                data_internal["ca_id_history"] = history

        return await self._crud_spaces.update(
            _id=_id, payload=CASpacePutInternal(**data_internal), fields=fields
        )

    async def delete_space(self, _id: str) -> None:
        certificates = await self._crud_certificates.search(
            space_id=_id, fields=["id"], limit=1
        )
        if certificates.meta.result_size > 0:
            raise QueryParamValidationError(
                msg=(
                    f"Space '{_id}' still contains "
                    f"{certificates.meta.result_size} certificates, cannot delete"
                )
            )
        await self._crud_spaces.delete(_id=_id)

    async def update_authority(
        self, ca_id: str, payload: CAAuthorityPut, fields: list
    ) -> CAAuthorityGet:
        data_internal = payload.model_dump(exclude_unset=True)
        if data_internal.pop("status", None) == "revoked":
            await self._require_unused_authority(ca_id)
            try:
                await self._crud_authorities.revoke(
                    _id=ca_id,
                    revocation_date=datetime.datetime.now(datetime.timezone.utc),
                )
            except ResourceNotFound:
                await self._crud_authorities.get(ca_id, fields=["id"], use_cache=False)
        if not data_internal:
            return await self._crud_authorities.get(
                ca_id, fields=fields, use_cache=False
            )
        return await self._crud_authorities.update(
            _id=ca_id, payload=CAAuthorityPutInternal(**data_internal), fields=fields
        )

    async def _spaces_using(self, ca_id: str) -> list[str]:
        spaces = await self._crud_spaces.search(
            ca_id=f"^{re.escape(ca_id)}$", fields=["id"]
        )
        return sorted(str(space.id) for space in spaces.result)

    async def _sub_authorities(
        self, ca_id: str, status: typing.Optional[str] = None
    ) -> list[str]:
        children = await self._crud_authorities.search(
            parent_id=f"^{re.escape(ca_id)}$", status=status, fields=["id"]
        )
        return sorted(str(child.id) for child in children.result)

    async def _require_unused_authority(self, ca_id: str) -> None:
        spaces = await self._spaces_using(ca_id)
        if spaces:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' is still used by spaces: {', '.join(spaces)}"
            )
        children = await self._sub_authorities(ca_id, status="active")
        if children:
            raise QueryParamValidationError(
                msg=(
                    f"CA Authority '{ca_id}' is still the parent of active "
                    f"authorities: {', '.join(children)}"
                )
            )

    async def authority_chain_revoked(self, ca_id: str) -> bool:
        path = await self._authority_path(ca_id)
        return any(authority.status == "revoked" for authority in path)

    async def _requested_sans(
        self, cn: str, ca: CAAuthorityGet, space: CASpaceGet, cert: CACertificateGet
    ) -> list[str]:
        if cert.requested_sans is not None:
            return list(cert.requested_sans)
        if cert.csr:
            return await self._run(crypto.csr_pem_dns_sans, self._clean_pem(cert.csr))
        injected = set(
            injected_sans(
                self.log, cn, [ca.validation_config, space.validation_config]
            )
        )
        sans = await self._run(
            crypto.certificate_dns_sans, self._clean_pem(cert.certificate)
        )
        return [san for san in sans if san != cn and san not in injected]

    async def delete_authority(self, ca_id: str) -> None:
        spaces = await self._spaces_using(ca_id)
        if spaces:
            raise QueryParamValidationError(
                msg=(
                    f"CA Authority '{ca_id}' is still used by spaces: "
                    f"{', '.join(spaces)}, cannot delete"
                )
            )

        children = await self._sub_authorities(ca_id)
        if children:
            raise QueryParamValidationError(
                msg=(
                    f"CA Authority '{ca_id}' is still the parent of authorities: "
                    f"{', '.join(children)}, cannot delete"
                )
            )

        await self._crud_authorities.delete(_id=ca_id)

    async def update_certificate_status(
        self, space_id: str, cn: str, payload: CACertificatePut, fields: list
    ) -> CACertificateGet:
        if payload.status not in ("signed", "revoked"):
            raise QueryParamValidationError(
                msg=f"Invalid transition to {payload.status} for certificate {cn}"
            )
        try:
            cert = await self._crud_certificates.get_active_by_cn(
                space_id=space_id, cn=cn, fields=[]
            )
        except ResourceNotFound:
            raise ResourceNotFound(
                details=f"Certificate for {cn} in space {space_id} not found"
            )

        if payload.status == "revoked":
            return await self.revoke_certificate(_id=str(cert.id))
        if cert.status == "signed":
            return cert
        return await self.process_requested_certificate(_id=str(cert.id))

    async def clean_certificate(self, space_id: str, cn: str) -> None:
        await self._crud_certificates.delete_requests(space_id=space_id, cn=cn)
        try:
            cert = await self._crud_certificates.get_active_by_cn(
                space_id=space_id, cn=cn, fields=["id", "status"]
            )
            if cert.status == "signed":
                await self.revoke_certificate(_id=str(cert.id))
        except ResourceNotFound:
            return

    async def update_certificate_status_by_ca(
        self, ca_id: str, cert_id: str, payload: CACertificatePut, fields: list
    ) -> CACertificateGet:
        if payload.status != "revoked":
            raise QueryParamValidationError(
                msg=f"Invalid transition to {payload.status} for active certificate"
            )
        try:
            cert = await self._crud_certificates.get(cert_id, fields=["ca_id"])
        except ResourceNotFound:
            raise ResourceNotFound(
                details=f"Certificate '{cert_id}' not found for CA '{ca_id}'"
            )
        if str(cert.ca_id) != str(ca_id):
            raise ResourceNotFound(
                details=f"Certificate '{cert_id}' not found for CA '{ca_id}'"
            )
        return await self.revoke_certificate(_id=cert_id)

    async def _get_signing_authority(self, ca_id: str) -> CAAuthorityGet:
        ca = await self._crud_authorities.get(ca_id, fields=[], use_cache=True)
        if ca.status == "revoked":
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' is revoked and cannot sign certificates"
            )
        return ca
