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
import uuid
import os
import re
import json
import httpx
import functools
from concurrent.futures import ThreadPoolExecutor
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.utils import CAUtils
from pyppetdb.errors import (
    ResourceNotFound,
    QueryParamValidationError,
    DuplicateResource,
)
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost,
    CAAuthorityGet,
    CAAuthorityPut,
)
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.model.ca_spaces import CASpaceGet, CASpacePost, CASpacePut
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
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
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

    async def _validate_csr(
        self,
        csr_pem: str,
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        ca_id: str,
        space_id: str,
    ):
        # 1. Cryptographic Integrity
        self._validate_csr_integrity(csr_pem)

        csr = x509.load_pem_x509_csr(csr_pem.encode())
        cn = csr.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value

        # 2. Subject Name Validation
        self._validate_csr_subject_name(cn, [ca_config, space_config])

        # 3. SAN Validation
        await self._validate_csr_sans(
            csr=csr,
            cn=cn,
            configs=[ca_config, space_config],
            ca_id=ca_id,
            space_id=space_id,
        )

    def _validate_csr_integrity(self, csr_pem: str):
        if not CAUtils.verify_csr_signature(csr_pem.encode()):
            raise QueryParamValidationError(msg="CSR signature is invalid")

    def _validate_csr_subject_name(self, cn: str, configs: list[CAValidationConfig]):
        for config in configs:
            if config and config.enforce_rfc1123:
                if not RE_RFC1123.match(cn):
                    raise QueryParamValidationError(
                        msg=f"CN '{cn}' does not follow strict RFC 1123 (lowercase) format"
                    )

    async def _validate_csr_sans(
        self,
        csr: x509.CertificateSigningRequest,
        cn: str,
        configs: list[CAValidationConfig],
        ca_id: str,
        space_id: str,
    ):
        san_ext = None
        try:
            san_ext = csr.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
        except x509.ExtensionNotFound:
            pass

        sans = []
        if san_ext:
            sans = san_ext.value.get_values_for_type(x509.DNSName)

        for config in configs:
            if not config or not config.san_validation:
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

    def _validate_sans_count(self, sans: list[str], max_count: int):
        if len(sans) > max_count:
            raise QueryParamValidationError(
                msg=f"Number of SANs ({len(sans)}) exceeds maximum allowed ({max_count})"
            )

    def _validate_sans_regex(self, sans: list[str], regex_list: list[str] | None):
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
            env[f"SAN{i+1}"] = san

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

    def _get_injected_sans(
        self, cn: str, configs: list[CAValidationConfig]
    ) -> list[str]:
        injected = set()
        for config in configs:
            if not config or not config.san_injection:
                continue
            for rule in config.san_injection:
                match = re.match(rule.pattern, cn)
                if match:
                    groups = [match.group(0)] + list(match.groups())
                    group_dict = match.groupdict()
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

        ca = await self._crud_authorities.get_cached(ca_id)
        ca_key_pem = await self._crud_authorities.get_private_key_cached(ca_id)

        ca_cert = x509.load_pem_x509_certificate(ca.certificate.encode())
        ca_key = serialization.load_pem_private_key(
            ca_key_pem,
            password=None,
        )

        self._cache[ca_id] = {
            "cert": ca_cert,
            "key": ca_key,
            "timestamp": now,
        }
        return ca_cert, ca_key

    async def refresh_crl(self, ca_id: str) -> None:
        """Regenerate CRL for an internal CA."""
        ca = await self._crud_authorities.get(ca_id, fields=["internal", "id"])
        if not ca.internal:
            return

        ca_cert_obj, ca_key_obj = await self._get_ca_resources(ca_id)

        revoked_cas = await self._crud_authorities.get_revoked(parent_id=ca_id)

        revoked_certs = await self._crud_certificates.get_revoked_for_ca(ca_id=ca_id)

        crl_pem, next_update = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(
                CAUtils.generate_crl,
                ca_cert=ca_cert_obj,
                ca_key=ca_key_obj,
                revoked_certs=revoked_cas + revoked_certs,
                validity_days=self.config.ca.crlValidityDays,
            ),
        )

        await self._crud_authorities.sync_crl_data(
            ca_id=ca_id,
            crl_pem=crl_pem.decode(),
            next_update=next_update,
        )

    async def refresh_all_internal_crls(self) -> None:
        self.log.info("Refreshing all internal CRLs...")
        ca_ids = await self._crud_authorities.get_all_internal_cas()

        for ca_id in ca_ids:
            if await self._crud_authorities.lock_crl_acquire(ca_id):
                self.log.info(f"Refreshing CRL for CA '{ca_id}'")
                try:
                    await self.refresh_crl(ca_id)
                except Exception as e:
                    self.log.error(f"Failed to refresh CRL for CA '{ca_id}': {e}")
                finally:
                    await self._crud_authorities.lock_crl_release(ca_id)
            else:
                self.log.debug(
                    f"CRL refresh for CA '{ca_id}' is already locked by another process"
                )

    async def crl_refresh_worker(self) -> None:
        while True:
            try:
                await self.refresh_all_internal_crls()
            except Exception as e:
                self.log.error(f"Error in CRL refresh worker: {e}")
            await asyncio.sleep(self._config.ca.crlRefreshInterval)

    async def create_authority(
        self, _id: str, payload: CAAuthorityPost, fields: list = None
    ) -> CAAuthorityGet:
        if fields is None:
            fields = ["id"]
        if payload.certificate and payload.private_key:
            internal = False
            cert_pem = payload.certificate.encode()
            key_pem = payload.private_key.encode()
            chain = payload.external_chain or []
        elif payload.parent_id:
            internal = True
            parent_ca = await self._crud_authorities.get(
                payload.parent_id, fields=["certificate", "chain"]
            )
            parent_key = await self._crud_authorities.get_private_key(payload.parent_id)
            cert_pem, key_pem = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                functools.partial(
                    CAUtils.sign_ca,
                    cn=payload.cn,
                    ca_cert_pem=parent_ca.certificate.encode(),
                    ca_key_pem=parent_key,
                    organization=payload.organization,
                    organizational_unit=payload.organizational_unit,
                    country=payload.country,
                    state=payload.state,
                    locality=payload.locality,
                    validity_days=payload.validity_days,
                ),
            )
            chain = [parent_ca.certificate] + parent_ca.chain
        else:
            internal = True
            cert_pem, key_pem = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                functools.partial(
                    CAUtils.generate_ca,
                    cn=payload.cn,
                    organization=payload.organization,
                    organizational_unit=payload.organizational_unit,
                    country=payload.country,
                    state=payload.state,
                    locality=payload.locality,
                    validity_days=payload.validity_days,
                ),
            )
            chain = []

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(
                CAUtils.get_cert_info,
                cert_pem=cert_pem,
            ),
        )
        encrypted_key = self._crud_authorities.protector.encrypt_string(
            key_pem.decode()
        )

        data = {
            "id": _id,
            "parent_id": payload.parent_id,
            "certificate": cert_pem.decode(),
            "private_key_encrypted": encrypted_key,
            "internal": internal,
            "chain": chain,
            "status": "active",
            "validation_config": (
                payload.validation_config.model_dump()
                if payload.validation_config
                else None
            ),
            **info,
        }

        if internal:
            crl_pem, next_update = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                functools.partial(
                    CAUtils.generate_crl,
                    ca_cert=cert_pem,
                    ca_key=key_pem,
                    revoked_certs=[],
                    validity_days=self.config.ca.crlValidityDays,
                ),
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            from pyppetdb.model.ca_authorities import CACRL

            data["crl"] = CACRL(
                crl_pem=crl_pem.decode(),
                generation=1,
                updated_at=now,
                next_update=next_update,
            ).model_dump()

        return await self._crud_authorities.insert(data, fields=fields)

    async def submit_certificate_request(
        self, space_id: str, csr_pem: str, fields: list = None, cn: str = None
    ) -> CACertificateGet:
        if fields is None:
            fields = ["id", "status", "ca_id"]

        try:
            csr_info = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                functools.partial(
                    CAUtils.get_csr_info,
                    csr_pem=csr_pem.encode(),
                ),
            )
        except Exception as e:
            raise QueryParamValidationError(msg=f"Invalid CSR: {e}")

        csr_cn = csr_info["cn"]

        if cn and cn != csr_cn:
            raise QueryParamValidationError(
                msg=f"CSR CN '{csr_cn}' does not match nodename '{cn}'"
            )

        space = await self._crud_spaces.get_cached(space_id)
        ca = await self._crud_authorities.get_cached(space.ca_id)

        await self._validate_csr(
            csr_pem=csr_pem,
            ca_config=ca.validation_config,
            space_config=space.validation_config,
            ca_id=ca.id,
            space_id=space_id,
        )

        # Check if already exists in 'requested' state to update it
        try:
            existing_requested = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=csr_cn, status="requested"
            )
        except ResourceNotFound:
            existing_requested = None

        if existing_requested:
            # Update existing request
            updated = await self._crud_certificates.update(
                query={"id": existing_requested.id},
                payload={"csr": csr_pem, **csr_info},
                fields=fields,
            )
            return updated

        # Check if already signed to avoid duplicates
        try:
            await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=csr_cn, status="signed"
            )
            raise DuplicateResource(
                msg=f"A signed certificate already exists for '{csr_cn}' in space '{space_id}'"
            )
        except ResourceNotFound:
            pass

        data = {
            "id": str(uuid.uuid4().int),
            "space_id": space_id,
            "ca_id": space.ca_id,
            "cn": csr_cn,
            "csr": csr_pem,
            "status": "requested",
            "cert_uniqueness": f"{space_id}:{csr_cn}",
            **csr_info,
        }

        return await self._crud_certificates.insert(data, fields=fields)

    async def sign_certificate(
        self, space_id: str, cn: str, fields: list = None
    ) -> CACertificateGet:
        try:
            cert_req = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="requested"
            )
        except ResourceNotFound:
            # For idempotency, if it's already active, return it
            try:
                return await self._crud_certificates.get_by_cn(
                    space_id=space_id, cn=cn, status="signed", fields=fields
                )
            except ResourceNotFound:
                raise ResourceNotFound(
                    details=f"Certificate request for {cn} in space {space_id} not found"
                )

        return await self.process_requested_certificate(cert_req.id)

    async def process_requested_certificate(self, _id: str) -> CACertificateGet:
        cert_req = await self._crud_certificates.get(_id, fields=None)
        if cert_req.status != "requested":
            raise QueryParamValidationError(
                msg=f"Certificate '{_id}' is in status '{cert_req.status}', expected 'requested'"
            )

        space = await self._crud_spaces.get_cached(cert_req.space_id)
        ca = await self._crud_authorities.get_cached(space.ca_id)

        ca_cert_obj, ca_key_obj = await self._get_ca_resources(space.ca_id)

        # CSR already validated in sign_certificate, but we might want to re-run injection
        cn = cert_req.cn
        allowed_exts = None
        if ca.validation_config and ca.validation_config.allowed_extensions is not None:
            allowed_exts = set(ca.validation_config.allowed_extensions)

        if (
            space.validation_config
            and space.validation_config.allowed_extensions is not None
        ):
            space_exts = set(space.validation_config.allowed_extensions)
            if allowed_exts is not None:
                allowed_exts = allowed_exts.intersection(space_exts)
            else:
                allowed_exts = space_exts
        if allowed_exts is not None:
            allowed_exts = list(allowed_exts)

        key_usages = None
        if space.validation_config and space.validation_config.key_usages is not None:
            key_usages = space.validation_config.key_usages
        elif ca.validation_config and ca.validation_config.key_usages is not None:
            key_usages = ca.validation_config.key_usages

        extended_key_usages = None
        if (
            space.validation_config
            and space.validation_config.extended_key_usages is not None
        ):
            extended_key_usages = space.validation_config.extended_key_usages
        elif (
            ca.validation_config
            and ca.validation_config.extended_key_usages is not None
        ):
            extended_key_usages = ca.validation_config.extended_key_usages

        injected_sans = self._get_injected_sans(
            cn, [ca.validation_config, space.validation_config]
        )

        cert_pem = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(
                CAUtils.sign_csr,
                csr_pem=cert_req.csr.encode(),
                ca_cert=ca_cert_obj,
                ca_key=ca_key_obj,
                validity_days=self._config.ca.certificateValidityDays,
                allowed_extensions=allowed_exts,
                injected_sans=injected_sans,
                key_usages=key_usages,
                extended_key_usages=extended_key_usages,
            ),
        )

        info = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(
                CAUtils.get_cert_info,
                cert_pem=cert_pem,
            ),
        )

        update_data = {
            "id": info["serial_number"],
            "certificate": cert_pem.decode(),
            "status": "signed",
            **info,
        }

        return await self._crud_certificates.update(
            query={"id": _id}, payload=update_data, fields=None
        )

    async def revoke_certificate(self, _id: str) -> CACertificateGet:
        cert = await self._crud_certificates.get(_id, fields=["status", "ca_id"])
        if cert.status == "revoked":
            return cert

        now = datetime.datetime.now(datetime.timezone.utc)
        result = await self._crud_certificates.update(
            query={"id": _id},
            payload={
                "status": "revoked",
                "revocation_date": now,
                "cert_uniqueness": f"revoked:{_id}",
            },
            fields=None,
        )

        return result

    async def renew_certificate(self, space_id: str, cn: str) -> CACertificateGet:
        try:
            old_cert = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="signed"
            )
        except ResourceNotFound:
            try:
                old_cert = await self._crud_certificates.get_by_cn(
                    space_id=space_id, cn=cn
                )
            except ResourceNotFound:
                raise ResourceNotFound(
                    details=f"Certificate for {cn} in space {space_id} not found"
                )

        if not old_cert.csr:
            # Backtrack: try to find a CSR in any other record for this CN
            # This handles cases where older versions might not have saved the CSR in the signed record
            self.log.debug(
                f"CSR missing in signed record for {cn}, searching in other records"
            )
            try:
                # Search for any record with this CN that has a CSR, sorted by created date descending
                search_res = await self._crud_certificates.search(
                    space_id=space_id, cn=cn, sort="created", sort_order="descending"
                )
                for cert in search_res.result:
                    if cert.csr:
                        old_cert.csr = cert.csr
                        break
            except Exception as e:
                self.log.error(f"Failed to backtrack CSR for {cn}: {e}")

        if not old_cert.csr:
            raise QueryParamValidationError(
                msg=f"No CSR found for certificate {cn}, cannot renew"
            )

        if old_cert.status == "signed":
            await self.revoke_certificate(old_cert.id)
        else:
            # If it was already revoked but uniqueness wasn't freed (legacy), free it now
            await self._crud_certificates.update(
                query={"id": old_cert.id},
                payload={"cert_uniqueness": f"revoked:{old_cert.id}"},
                fields=None,
            )

        # Submit a NEW request using the same CSR
        await self.submit_certificate_request(
            space_id=space_id, csr_pem=old_cert.csr, cn=cn
        )

        # Sign it
        return await self.sign_certificate(space_id=space_id, cn=cn)

    async def revoke_authority(self, _id: str) -> CAAuthorityGet:
        ca = await self._crud_authorities.get(_id, fields=["status", "parent_id"])
        if ca.status == "revoked":
            return ca

        now = datetime.datetime.now(datetime.timezone.utc)
        result = await self._crud_authorities.update(
            query={"id": _id},
            payload={"status": "revoked", "revocation_date": now},
            fields=None,
        )

        # Refresh parent CRL if exists
        if ca.parent_id:
            await self.refresh_crl(ca.parent_id)

        return result

    async def create_space(
        self, _id: str, payload: CASpacePost, fields: list = None
    ) -> CASpaceGet:
        data = payload.model_dump()
        data["id"] = _id
        return await self._crud_spaces.insert(data, fields=fields)

    async def update_space(
        self, _id: str, payload: CASpacePut, fields: list = None
    ) -> CASpaceGet:
        query = {"id": _id}
        data = payload.model_dump(exclude_unset=True)
        return await self._crud_spaces.update(query=query, payload=data, fields=fields)

    async def delete_space(self, _id: str) -> None:
        await self._crud_spaces.delete(query={"id": _id})

    async def update_authority(
        self, ca_id: str, payload: CAAuthorityPut, fields: list = None
    ) -> CAAuthorityGet:
        query = {"id": ca_id}
        data = payload.model_dump(exclude_unset=True)
        return await self._crud_authorities.update(
            query=query, payload=data, fields=fields
        )

    async def delete_authority(self, ca_id: str) -> None:
        await self._crud_authorities.delete(_id=ca_id)

    async def update_certificate_status(
        self, space_id: str, cn: str, payload: CACertificatePut, fields: list = None
    ) -> CACertificateGet:
        try:
            cert = await self._crud_certificates.get_by_cn(
                space_id=space_id, cn=cn, status="requested"
            )
        except ResourceNotFound:
            try:
                cert = await self._crud_certificates.get_by_cn(
                    space_id=space_id, cn=cn, status="signed"
                )
            except ResourceNotFound:
                raise ResourceNotFound(
                    details=f"Certificate for {cn} in space {space_id} not found"
                )

        if payload.status == "signed":
            if cert.status == "signed":
                return cert
            return await self.process_requested_certificate(_id=cert.id)
        elif payload.status == "revoked":
            return await self.revoke_certificate(_id=cert.id)
        else:
            raise QueryParamValidationError(
                msg=f"Invalid transition to {payload.status} for certificate in status {cert.status}"
            )

    async def update_certificate_status_by_ca(
        self, ca_id: str, cert_id: str, payload: CACertificatePut, fields: list = None
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
        space = await self._crud_spaces.get_cached(space_id)
        ca_id_path = [space.ca_id]

        # Resolve chain of parent IDs
        current_ca_id = space.ca_id
        while True:
            ca = await self._crud_authorities.get(current_ca_id, fields=["parent_id"])
            if ca.parent_id:
                ca_id_path.append(ca.parent_id)
                current_ca_id = ca.parent_id
            else:
                break

        crl_chain_pem = b""
        for ca_id in ca_id_path:
            ca = await self._crud_authorities.get(
                ca_id, fields=["crl", "internal", "parent_id"]
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
        space = await self._crud_spaces.get_cached(space_id)
        ca_id_path = [space.ca_id]

        # Resolve chain of parent IDs
        current_ca_id = space.ca_id
        while True:
            ca = await self._crud_authorities.get(current_ca_id, fields=["parent_id"])
            if ca.parent_id:
                ca_id_path.append(ca.parent_id)
                current_ca_id = ca.parent_id
            else:
                break

        cert_chain_pem = b""
        for ca_id in ca_id_path:
            ca = await self._crud_authorities.get(ca_id, fields=["certificate"])
            if ca.certificate:
                cert_chain_pem += ca.certificate.encode()

        return cert_chain_pem
