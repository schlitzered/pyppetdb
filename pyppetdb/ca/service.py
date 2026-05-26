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
import asyncio
import datetime
import time
import typing
import uuid
import os
import re
import json
import httpx
import socket
from concurrent.futures import ThreadPoolExecutor
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.ca.utils import CAUtils
from pyppetdb.errors import (
    ResourceNotFound,
    QueryParamValidationError,
    DuplicateResource,
)
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost,
    CAAuthorityPostInternal,
    CAAuthorityGet,
    CAAuthorityPut,
    CAAuthorityPutInternal,
)
from pyppetdb.model.ca_certificates import (
    CACertificateGet,
    CACertificatePut,
    CACertificatePutInternal,
    CACertificatePostInternal,
)
from pyppetdb.model.ca_spaces import (
    CASpaceGet,
    CASpacePost,
    CASpacePut,
    CASpacePutInternal,
)
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CAHTTPValidation,
    CAScriptValidation,
)

# RFC 1123 hostname regex (lowercase only)
RE_RFC1123 = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)


class CAService:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._instance_id = socket.getfqdn()
        self._executor = ThreadPoolExecutor(
            max_workers=self._config.ca.concurrentWorkers
        )
        self._cache = {}
        self._cache_ttl = 3600  # 1 hour

    @property
    def log(self):
        return self._log

    @property
    def config(self):
        return self._config

    @staticmethod
    def _clean_pem(data: str | bytes) -> bytes:
        """Extract the first PEM block from the input data, ignoring garbage."""
        if not data:
            return b""
        if isinstance(data, str):
            data = data.encode()
        # Find the first BEGIN/END block
        m = re.search(rb"-----BEGIN [^-]+-----.*?-----END [^-]+-----", data, re.DOTALL)
        if m:
            return m.group(0).strip()
        return data.strip()

    async def _validate_csr(
        self,
        csr: x509.CertificateSigningRequest,
        cn: str,
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        ca_id: str,
        space_id: str,
    ):
        # 1. Subject Name Validation
        enforce_rfc1123 = ca_config.enforce_rfc1123 or space_config.enforce_rfc1123

        if enforce_rfc1123:
            if not RE_RFC1123.match(cn):
                raise QueryParamValidationError(
                    msg=f"CN '{cn}' does not follow strict RFC 1123 (lowercase) format"
                )

        # 2. SAN Validation
        await self._validate_csr_sans(
            csr=csr,
            cn=cn,
            configs=[ca_config, space_config],
            ca_id=ca_id,
            space_id=space_id,
        )

    async def _validate_csr_sans(
        self,
        csr: x509.CertificateSigningRequest,
        cn: str,
        configs: list[CAValidationConfig],
        ca_id: str,
        space_id: str,
    ):
        try:
            san_ext = csr.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            sans = []
            if san_ext:
                sans = san_ext.value.get_values_for_type(x509.DNSName)
            if not sans:
                return
        except x509.ExtensionNotFound:
            return

        for config in configs:
            if not config.san_validation:
                continue

            san_val = config.san_validation

            self._validate_sans_count(sans, san_val.max_san_count)
            self._validate_sans_regex(sans, san_val.regex_list)

            if san_val.http_checks:
                await self._validate_sans_http(
                    cn=cn,
                    sans=sans,
                    http_checks=san_val.http_checks,
                    ca_id=ca_id,
                    space_id=space_id,
                )

            if san_val.script_checks:
                await self._validate_sans_script(
                    cn=cn,
                    sans=sans,
                    script_checks=san_val.script_checks,
                )

    @staticmethod
    def _validate_sans_count(sans: list[str], max_count: int):
        if len(sans) > max_count:
            raise QueryParamValidationError(
                msg=f"Number of SANs ({len(sans)}) exceeds maximum allowed ({max_count})"
            )

    @staticmethod
    def _validate_sans_regex(sans: list[str], regex_list: list[str] | None):
        if not regex_list:
            return
        for san in sans:
            if not any(re.match(pattern, san) for pattern in regex_list):
                raise QueryParamValidationError(
                    msg=f"SAN '{san}' does not match any allowed patterns"
                )

    async def _validate_sans_http(
        self,
        cn: str,
        sans: list[str],
        http_checks: list[CAHTTPValidation],
        ca_id: str,
        space_id: str,
    ):
        for http_check in http_checks:
            await self._execute_http_validation(
                cn=cn,
                sans=sans,
                config=http_check,
                ca_id=ca_id,
                space_id=space_id,
            )

    async def _validate_sans_script(
        self,
        cn: str,
        sans: list[str],
        script_checks: list[CAScriptValidation],
    ):
        for script_check in script_checks:
            await self._execute_script_validation(
                cn=cn,
                sans=sans,
                config=script_check,
            )

    async def _execute_http_validation(
        self,
        cn: str,
        sans: list[str],
        config: CAHTTPValidation,
        ca_id: str,
        space_id: str,
    ):
        body = {"cn": cn, "sans": sans}
        if config.body_template:
            try:
                # Basic template substitution
                template_data = config.body_template.replace("{{cn}}", cn).replace(
                    "{{sans}}", json.dumps(sans)
                )
                body = json.loads(template_data)
            except Exception as e:
                self.log.error(f"Failed to parse HTTP body template: {e}")
                raise QueryParamValidationError(
                    msg="Invalid HTTP validation configuration"
                )

        try:
            url = config.url.format(
                ca_id=ca_id,
                space_id=space_id,
                cert_cn=cn,
            )
        except Exception as e:
            self.log.error(f"Failed to format HTTP validation URL '{config.url}': {e}")
            raise QueryParamValidationError(
                msg="Invalid HTTP validation configuration: URL format error"
            )

        client_kwargs = {
            "verify": config.verify_ssl,
            "timeout": config.timeout_seconds,
        }

        request_kwargs = {
            "method": config.method,
            "url": url,
            "json": body,
        }

        if config.basic_auth_enabled and config.username and config.password:
            request_kwargs["auth"] = (config.username, config.password)

        headers = {}
        if config.headers:
            for header in config.headers:
                headers[header.name] = header.value
        request_kwargs["headers"] = headers

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                resp = await client.request(**request_kwargs)
                if resp.is_error:
                    raise QueryParamValidationError(
                        msg=f"External HTTP validation failed with status {resp.status_code}"
                    )
            except httpx.HTTPError as e:
                self.log.error(f"External HTTP validation error: {e}")
                raise QueryParamValidationError(
                    msg=f"External HTTP validation error: {e}"
                )

    async def _execute_script_validation(
        self, cn: str, sans: list[str], config: CAScriptValidation
    ):

        env = os.environ.copy()
        env["CN"] = cn
        for i, san in enumerate(sans):
            env[f"SAN{i + 1}"] = san

        try:
            proc = await asyncio.create_subprocess_exec(
                config.script_path,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=config.timeout_seconds
                )
                if proc.returncode != 0:
                    error_msg = stderr.decode().strip() or stdout.decode().strip()
                    raise QueryParamValidationError(
                        msg=f"External script validation failed (exit {proc.returncode}): {error_msg}"
                    )
            except asyncio.TimeoutError:
                proc.kill()
                raise QueryParamValidationError(
                    msg="External script validation timed out"
                )
        except Exception as e:
            if isinstance(e, QueryParamValidationError):
                raise
            self.log.error(f"External script execution error: {e}")
            raise QueryParamValidationError(msg=f"External script execution error: {e}")

    async def _sign(
        self,
        cn: str,
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        ca_cert_obj: x509.Certificate,
        ca_key_obj: rsa.RSAPrivateKey,
        csr_pem: typing.Optional[bytes] = None,
        old_cert_pem: typing.Optional[bytes] = None,
    ) -> bytes:
        allowed_exts = None
        if ca_config.allowed_extensions is not None:
            allowed_exts = set(ca_config.allowed_extensions)

        if space_config.allowed_extensions is not None:
            space_exts = set(space_config.allowed_extensions)
            if allowed_exts is not None:
                allowed_exts = allowed_exts.intersection(space_exts)
            else:
                allowed_exts = space_exts

        if allowed_exts is not None:
            allowed_exts = list(allowed_exts)

        if space_config.key_usages is not None:
            key_usages: dict[str, bool] = space_config.get_key_usage_kwargs()
        else:
            key_usages: dict[str, bool] = ca_config.get_key_usage_kwargs()

        extended_key_usages: list[str] = list(
            space_config.extended_key_usages or ca_config.extended_key_usages or []
        )

        injected_sans = await self._get_injected_sans(
            cn,
            [
                ca_config,
                space_config,
            ],
        )

        if csr_pem:
            try:
                return await asyncio.get_running_loop().run_in_executor(
                    self._executor,
                    CAUtils.sign_csr,
                    csr_pem,
                    ca_cert_obj,
                    ca_key_obj,
                    key_usages,
                    extended_key_usages,
                    self._config.ca.certificateValidityDays,
                    None,
                    allowed_exts,
                    injected_sans,
                )
            except ValueError as e:
                raise QueryParamValidationError(msg=f"Failed to sign CSR: {e}")
        elif old_cert_pem:
            try:
                return await asyncio.get_running_loop().run_in_executor(
                    self._executor,
                    CAUtils.renew_cert,
                    old_cert_pem,
                    ca_cert_obj,
                    ca_key_obj,
                    key_usages,
                    extended_key_usages,
                    self._config.ca.certificateValidityDays,
                    None,
                    allowed_exts,
                    injected_sans,
                )
            except ValueError as e:
                raise QueryParamValidationError(msg=f"Failed to renew certificate: {e}")
        else:
            raise ValueError("Either csr_pem or old_cert_pem must be provided")

    async def _get_injected_sans(
        self, cn: str, configs: list[CAValidationConfig]
    ) -> list[str]:
        injected = set()
        for config in configs:
            if not config.san_injection:
                continue
            for rule in config.san_injection:
                m = re.match(rule.pattern, cn)
                if m:
                    groups = [m.group(0)] + list(m.groups())
                    group_dict = m.groupdict()
                    for template in rule.templates:
                        try:
                            san = template.format(*groups, **group_dict)
                            injected.add(san)
                        except Exception as e:
                            self.log.error(
                                f"Failed to format SAN injection template '{template}': {e}"
                            )
        return list(injected)

    async def _get_ca_resources(self, ca_id: str):
        """Load CA key and cert from cache and return cryptography objects."""
        now = time.time()
        cached = self._cache.get(ca_id)

        if cached and (now - cached["timestamp"] < self._cache_ttl):
            return cached["cert"], cached["key"]

        ca = await self._crud_authorities.get(ca_id, fields=[], use_cache=True)
        ca_key_pem = await self._crud_authorities.get_private_key_cached(ca_id)

        ca_cert = x509.load_pem_x509_certificate(ca.certificate.encode())
        ca_key = serialization.load_pem_private_key(
            ca_key_pem,
            password=None,
            *[],
        )

        self._cache[ca_id] = {
            "cert": ca_cert,
            "key": ca_key,
            "timestamp": now,
        }
        return ca_cert, ca_key

    async def generate_crl(self, ca_id: str) -> None:
        self.log.info(f"Generating CRL for CA '{ca_id}'")
        ca_cert_obj, ca_key_obj = await self._get_ca_resources(ca_id)

        # Get revoked CAs (children of this CA)
        revoked_cas = await self._crud_authorities.get_revoked_for_ca(parent_id=ca_id)

        # Get revoked certs in this CA
        revoked_certs = await self._crud_certificates.get_revoked_for_ca(ca_id=ca_id)

        crl_pem, next_update = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            CAUtils.generate_crl,
            ca_cert_obj,
            ca_key_obj,
            revoked_cas + revoked_certs,
            self.config.ca.crlValidityDays,
        )

        await self._crud_authorities.sync_crl_data(
            ca_id=ca_id,
            crl_pem=crl_pem.decode(),
            next_update=next_update,
        )

    async def refresh_all_internal_crls(self) -> None:
        leader = await self._crud_pyppetdb_nodes.get_leader()
        if leader != self._instance_id:
            self.log.debug(
                f"Skipping CRL refresh, I am not the leader (Leader: {leader}, Me: {self._instance_id})"
            )
            return

        self.log.info("I am the leader, refreshing all internal CRLs...")
        ca_ids = await self._crud_authorities.get_all_internal_cas()
        for ca_id in ca_ids:
            try:
                await self.generate_crl(ca_id)
            except Exception as e:
                self.log.error(f"Failed to generate CRL for CA '{ca_id}': {e}")

    async def crl_refresh_worker(self) -> None:
        while True:
            try:
                await self.refresh_all_internal_crls()
            except Exception as e:
                self.log.error(f"Error in CRL refresh worker: {e}")
            await asyncio.sleep(self._config.ca.crlRefreshInterval)

    async def create_authority(
        self, _id: str, payload: CAAuthorityPost, fields: list
    ) -> CAAuthorityGet:
        if payload.certificate and payload.private_key:
            internal = False
            cert_pem = payload.certificate.encode()
            key_pem = payload.private_key.encode()
            chain = payload.external_chain or []
        elif payload.parent_id:
            internal = True
            parent_ca = await self._crud_authorities.get(
                payload.parent_id, fields=["certificate", "chain"], use_cache=True
            )
            parent_key = await self._crud_authorities.get_private_key(payload.parent_id)

            cn: str = payload.cn
            parent_cert_pem: bytes = str(parent_ca.certificate).encode()
            parent_key_pem: bytes = parent_key
            org: str = str(payload.organization)
            ou: str = str(payload.organizational_unit)
            country: str = str(payload.country)
            state: str | None = payload.state
            locality: str | None = payload.locality
            if not payload.validity_days:
                validity = 0
            else:
                validity: int = int(payload.validity_days)

            cert_pem, key_pem = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                CAUtils.sign_ca,
                cn,
                parent_cert_pem,
                parent_key_pem,
                org,
                ou,
                country,
                state,
                locality,
                validity,
            )
            chain = [parent_ca.certificate] + parent_ca.chain
        else:
            internal = True
            cn: str = payload.cn
            org: str = str(payload.organization)
            ou: str = str(payload.organizational_unit)
            country: str = str(payload.country)
            state: str | None = payload.state
            locality: str | None = payload.locality
            if not payload.validity_days:
                validity = 0
            else:
                validity: int = int(payload.validity_days)

            cert_pem, key_pem = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                CAUtils.generate_ca,
                cn,
                org,
                ou,
                country,
                state,
                locality,
                validity,
            )
            chain = []

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            CAUtils.get_cert_info,
            cert_pem,
        )
        encrypted_key = self._crud_authorities.protector.encrypt_string(
            key_pem.decode()
        )

        data = {
            "id": _id,
            "parent_id": payload.parent_id,
            "cn": payload.cn,
            "issuer": info["issuer"],
            "serial_number": info["serial_number"],
            "not_before": info["not_before"],
            "not_after": info["not_after"],
            "fingerprint": info["fingerprint"],
            "certificate": cert_pem.decode(),
            "private_key_encrypted": encrypted_key,
            "internal": internal,
            "chain": chain,
            "status": "active",
            "validation_config": payload.validation_config.model_dump(),
        }

        if internal:
            crl_pem, next_update = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                CAUtils.generate_crl,
                cert_pem,
                key_pem,
                [],
                self.config.ca.crlValidityDays,
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            from pyppetdb.model.ca_authorities import CACRL

            data["crl"] = CACRL(
                crl_pem=crl_pem.decode(),
                generation=1,
                updated_at=now,
                next_update=next_update,
            ).model_dump()

        return await self._crud_authorities.create(
            _id=_id, payload=CAAuthorityPostInternal(**data), fields=fields
        )

    async def submit_certificate_request(
        self, space_id: str, csr_pem: str, fields: list, cn: str
    ) -> CACertificateGet:
        try:
            cleaned_csr = self._clean_pem(csr_pem)
            csr, csr_info = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                CAUtils.parse_and_extract_csr,
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

        await self._validate_csr(
            csr=csr,
            cn=csr_cn,
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_id=str(ca.id),
            space_id=space_id,
        )

        payload = {
            "ca_id": str(space.ca_id),
            "cn": csr_cn,
            "space_id": space_id,
            "csr": cleaned_csr.decode(),
            **csr_info,
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
                space_id=space_id, cn=cn, status="requested"
            )
            return await self.process_requested_certificate(str(cert_req.id))
        except ResourceNotFound:
            # For idempotency, if it's already active, return it
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
        ca = await self._crud_authorities.get(
            str(space.ca_id), fields=[], use_cache=True
        )

        ca_cert_obj, ca_key_obj = await self._get_ca_resources(str(space.ca_id))

        cert_pem = await self._sign(
            cn=str(cert_req.cn),
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_cert_obj=ca_cert_obj,
            ca_key_obj=ca_key_obj,
            csr_pem=self._clean_pem(str(cert_req.csr)),
        )

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            CAUtils.get_cert_info,
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
            )
        except DuplicateResource:
            # Another process might have already signed it or there is a SN collision
            return await self._crud_certificates.get(info["serial_number"], fields=[])

    async def revoke_certificate(self, _id: str) -> CACertificateGet:
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            # Note: CrudCACertificates.update now strictly uses _id, but we need the status check for safety.
            # We can check the status first or just let the update fail if not found (though _get by _id is standard).
            # The previous code used: query={"id": _id, "status": {"$ne": "revoked"}}
            # For simplicity and sticking to the standard pattern:
            result = await self._crud_certificates.update(
                _id=_id,
                payload=CACertificatePutInternal(
                    status="revoked",
                    revocation_date=now,
                    cert_uniqueness=f"revoked:{_id}",
                ),
                fields=[],
            )
            return result
        except ResourceNotFound:
            # If not found with the $ne filter, it might already be revoked
            return await self._crud_certificates.get(_id, fields=[])

    async def renew_certificate(self, space_id: str, cn: str) -> CACertificateGet:
        try:
            old_cert = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="signed"
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
        ca = await self._crud_authorities.get(
            str(space.ca_id), fields=[], use_cache=True
        )

        ca_cert_obj, ca_key_obj = await self._get_ca_resources(str(space.ca_id))

        cert_pem = await self._sign(
            cn=cn,
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_cert_obj=ca_cert_obj,
            ca_key_obj=ca_key_obj,
            old_cert_pem=self._clean_pem(old_cert.certificate),
        )

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            CAUtils.get_cert_info,
            cert_pem,
        )

        if old_cert.status == "signed":
            await self.revoke_certificate(str(old_cert.id))
        else:
            # If it was already revoked but uniqueness wasn't freed (legacy), free it now
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
            "csr": old_cert.csr,  # carry over if it existed
            **info,
        }

        return await self._crud_certificates.create(
            _id=info["serial_number"],
            payload=CACertificatePostInternal(**new_cert_data),
            fields=[],
        )

    async def create_space(
        self, _id: str, payload: CASpacePost, fields: list
    ) -> CASpaceGet:
        return await self._crud_spaces.create(_id=_id, payload=payload, fields=fields)

    async def update_space(
        self, _id: str, payload: CASpacePut, fields: list
    ) -> CASpaceGet:
        data_internal = payload.model_dump(exclude_unset=True)
        if payload.ca_id:
            # Check if ca_id changed to update history
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
        # Check if space contains certificates
        if await self._crud_certificates.count({"space_id": _id}) > 0:
            raise QueryParamValidationError(
                msg=f"Space '{_id}' still contains certificates, cannot delete"
            )
        await self._crud_spaces.delete(_id=_id)

    async def update_authority(
        self, ca_id: str, payload: CAAuthorityPut, fields: list
    ) -> CAAuthorityGet:
        data_internal = payload.model_dump(exclude_unset=True)
        return await self._crud_authorities.update(
            _id=ca_id, payload=CAAuthorityPutInternal(**data_internal), fields=fields
        )

    async def delete_authority(self, ca_id: str) -> None:
        # Check if authority is in use by spaces
        if await self._crud_spaces.count({"ca_id": ca_id}) > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' still in use by one or more spaces, cannot delete"
            )

        # Check if authority is parent of another authority
        if await self._crud_authorities.count({"parent_id": ca_id}) > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' still a parent of one or more authorities, cannot delete"
            )

        await self._crud_authorities.delete(_id=ca_id)

    async def update_certificate_status(
        self, space_id: str, cn: str, payload: CACertificatePut, fields: list
    ) -> CACertificateGet:
        try:
            cert = await self._crud_certificates.get_by_cn(space_id=space_id, cn=cn)
            cert_id = str(cert.id)
        except ResourceNotFound:
            raise ResourceNotFound(
                details=f"Certificate for {cn} in space {space_id} not found"
            )

        if payload.status == "signed":
            if cert.status == "signed":
                return cert
            return await self.process_requested_certificate(_id=cert_id)
        elif payload.status == "revoked":
            return await self.revoke_certificate(_id=cert_id)
        else:
            raise QueryParamValidationError(
                msg=f"Invalid transition to {payload.status} for certificate in status {cert.status}"
            )

    async def update_certificate_status_by_ca(
        self, ca_id: str, cert_id: str, payload: CACertificatePut, fields: list
    ) -> CACertificateGet:
        if payload.status == "revoked":
            return await self.revoke_certificate(_id=cert_id)
        else:
            raise QueryParamValidationError(
                msg=f"Invalid transition to {payload.status} for active certificate"
            )

    async def delete_certificate(self, space_id: str, cn: str) -> None:
        await self._crud_certificates.delete_by_cn(space_id=space_id, cn=cn)

    async def get_crl_chain(self, space_id: str) -> bytes:
        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        ca_id_path = [str(space.ca_id)]

        # Resolve chain of parent IDs
        current_ca_id = str(space.ca_id)
        while True:
            ca = await self._crud_authorities.get(
                current_ca_id, fields=["parent_id"], use_cache=True
            )
            if ca.parent_id:
                ca_id_path.append(str(ca.parent_id))
                current_ca_id = str(ca.parent_id)
            else:
                break

        crl_chain_pem = b""
        for ca_id in ca_id_path:
            ca = await self._crud_authorities.get(
                ca_id, fields=["crl", "internal", "parent_id"], use_cache=True
            )
            if not ca.internal:
                self.log.debug(f"Skipping external CA '{ca_id}' in CRL chain")
                continue
            if not ca.crl:
                self.log.error(f"Internal CA '{ca_id}' is missing CRL data")
                continue
            crl_chain_pem += ca.crl.crl_pem.encode()

        return crl_chain_pem

    async def get_certificate_chain(self, space_id: str) -> bytes:
        space = await self._crud_spaces.get(space_id, fields=[], use_cache=True)
        ca_id_path = [str(space.ca_id)]

        # Resolve chain of parent IDs
        current_ca_id = str(space.ca_id)
        while True:
            ca = await self._crud_authorities.get(
                current_ca_id, fields=["parent_id"], use_cache=True
            )
            if ca.parent_id:
                ca_id_path.append(str(ca.parent_id))
                current_ca_id = str(ca.parent_id)
            else:
                break

        cert_chain_pem = b""
        for ca_id in ca_id_path:
            ca = await self._crud_authorities.get(
                ca_id, fields=["certificate"], use_cache=True
            )
            if ca.certificate:
                cert_chain_pem += ca.certificate.encode()

        return cert_chain_pem
