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
import contextlib
import json
import logging
import os
import re
import ssl
import tempfile
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import Optional
from urllib.parse import quote

import httpx
from cryptography import x509

from pyppetdb.ca import crypto
from pyppetdb.ca.policy import honor_requested_sans
from pyppetdb.ca.secrets import resolve_check
from pyppetdb.crud.ca_secrets import CrudCASecrets
from pyppetdb.errors import MissingSecretReference
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation
from pyppetdb.model.ca_validation import CAScriptValidation
from pyppetdb.model.ca_validation import CAValidationConfig

RE_RFC1123 = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)

SCRIPT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@contextlib.contextmanager
def pem_file(content: str) -> Iterator[str]:
    data = content.encode()
    memfd_create = getattr(os, "memfd_create", None)
    if memfd_create is not None:
        fd = memfd_create("pyppetdb-tls", os.MFD_CLOEXEC)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            yield f"/proc/self/fd/{fd}"
        finally:
            os.close(fd)
        return
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def script_environment(cn: str, sans: List[str]) -> dict[str, str]:
    env = {"PATH": SCRIPT_PATH, "CN": cn}
    for index, san in enumerate(sans, start=1):
        env[f"SAN{index}"] = san
    return env


class CSRValidator:
    def __init__(self, log: logging.Logger, crud_secrets: CrudCASecrets):
        self._log = log
        self._crud_secrets = crud_secrets

    @property
    def log(self) -> logging.Logger:
        return self._log

    async def validate(
        self,
        csr: x509.CertificateSigningRequest,
        cn: str,
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        ca_id: str,
        space_id: str,
        secret_refs: Iterable[str] = (),
    ) -> None:
        await self.validate_names(
            cn=cn,
            sans=crypto.csr_dns_sans(csr),
            ca_config=ca_config,
            space_config=space_config,
            ca_id=ca_id,
            space_id=space_id,
            secret_refs=secret_refs,
        )

    async def validate_names(
        self,
        cn: str,
        sans: List[str],
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        ca_id: str,
        space_id: str,
        secret_refs: Iterable[str] = (),
    ) -> None:
        enforce_rfc1123 = ca_config.enforce_rfc1123 or space_config.enforce_rfc1123
        if enforce_rfc1123 and not RE_RFC1123.match(cn):
            raise QueryParamValidationError(
                msg=f"CN '{cn}' does not follow strict RFC 1123 (lowercase) format"
            )
        if enforce_rfc1123 and sans and honor_requested_sans(ca_config, space_config):
            self.validate_sans_rfc1123(sans)
        secrets = await self._load_secrets(ca_config, space_config, secret_refs)
        for config in (ca_config, space_config):
            if not config.san_validation:
                continue
            san_validation = config.san_validation
            if sans:
                self.validate_sans_count(sans, san_validation.max_san_count)
                self.validate_sans_regex(sans, san_validation.regex_list)
            for http_check in san_validation.http_checks or []:
                await self.run_http_check(
                    cn=cn,
                    sans=sans,
                    config=http_check,
                    ca_id=ca_id,
                    space_id=space_id,
                    secrets=secrets,
                )
            for script_check in san_validation.script_checks or []:
                await self.run_script_check(cn=cn, sans=sans, config=script_check)

    @staticmethod
    def validate_sans_rfc1123(sans: List[str]) -> None:
        for san in sans:
            if not RE_RFC1123.match(san):
                raise QueryParamValidationError(
                    msg=f"SAN '{san}' does not follow strict RFC 1123 (lowercase) format"
                )

    @staticmethod
    def validate_sans_count(sans: List[str], max_count: int) -> None:
        if len(sans) > max_count:
            raise QueryParamValidationError(
                msg=f"Number of SANs ({len(sans)}) exceeds maximum allowed ({max_count})"
            )

    @staticmethod
    def validate_sans_regex(sans: List[str], regex_list: List[str] | None) -> None:
        if not regex_list:
            return
        for san in sans:
            if not any(re.fullmatch(pattern, san) for pattern in regex_list):
                raise QueryParamValidationError(
                    msg=f"SAN '{san}' does not match any allowed patterns"
                )

    @staticmethod
    def build_tls_verify(config: CAHTTPValidation) -> bool | ssl.SSLContext:
        client_cert_present = bool(config.client_cert and config.client_key)
        if not config.ca_cert and not client_cert_present:
            return config.verify_ssl
        ctx = ssl.create_default_context()
        if config.ca_cert:
            ctx.load_verify_locations(cadata=config.ca_cert)
        if not config.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if client_cert_present:
            with pem_file(config.client_cert) as cert_path, pem_file(
                config.client_key
            ) as key_path:
                ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return ctx

    async def _load_secrets(
        self,
        ca_config: CAValidationConfig,
        space_config: CAValidationConfig,
        secret_refs: Iterable[str],
    ) -> dict[str, str]:
        refs = set(secret_refs)
        has_http_checks = any(
            config.san_validation and config.san_validation.http_checks
            for config in (ca_config, space_config)
        )
        if not refs or not has_http_checks:
            return {}
        return await self._crud_secrets.get_values(refs)

    def _resolve_secrets(
        self, cn: str, config: CAHTTPValidation, secrets: Mapping[str, str]
    ) -> CAHTTPValidation:
        try:
            return resolve_check(config, secrets)
        except MissingSecretReference as err:
            self.log.error(
                f"HTTP validation for CN '{cn}' references unknown secret "
                f"'{err.secret_id}'"
            )
            raise QueryParamValidationError(
                msg="HTTP validation references an unknown secret"
            )

    def _request_body(self, cn: str, sans: List[str], config: CAHTTPValidation):
        if not config.body_template:
            return {"cn": cn, "sans": sans}
        try:
            return json.loads(
                config.body_template.replace("{{cn}}", json.dumps(cn)[1:-1]).replace(
                    "{{sans}}", json.dumps(sans)
                )
            )
        except Exception as err:
            self.log.error(f"Failed to parse HTTP body template: {err}")
            raise QueryParamValidationError(msg="Invalid HTTP validation configuration")

    def _request_url(self, cn: str, config: CAHTTPValidation, ca_id: str, space_id: str):
        try:
            return config.url.format(
                ca_id=ca_id, space_id=space_id, cert_cn=quote(cn, safe="")
            )
        except Exception as err:
            self.log.error(f"Failed to format HTTP validation URL '{config.url}': {err}")
            raise QueryParamValidationError(
                msg="Invalid HTTP validation configuration: URL format error"
            )

    def _tls_verify(self, config: CAHTTPValidation) -> bool | ssl.SSLContext:
        try:
            return self.build_tls_verify(config)
        except (ssl.SSLError, ValueError, OSError) as err:
            self.log.error(f"Invalid TLS settings for HTTP validation '{config.url}': {err}")
            raise QueryParamValidationError(
                msg="Invalid HTTP validation configuration: TLS settings"
            )

    async def run_http_check(
        self,
        cn: str,
        sans: List[str],
        config: CAHTTPValidation,
        ca_id: str,
        space_id: str,
        secrets: Optional[Mapping[str, str]] = None,
    ) -> None:
        config = self._resolve_secrets(cn, config, secrets or {})
        request_kwargs = {
            "method": config.method,
            "url": self._request_url(cn, config, ca_id, space_id),
            "json": self._request_body(cn, sans, config),
            "headers": {header.name: header.value for header in config.headers or []},
        }
        if config.basic_auth_enabled and config.username and config.password:
            request_kwargs["auth"] = (config.username, config.password)
        async with httpx.AsyncClient(
            verify=self._tls_verify(config), timeout=config.timeout_seconds
        ) as client:
            try:
                resp = await client.request(**request_kwargs)
            except httpx.HTTPError as err:
                self.log.error(
                    f"External HTTP validation for CN '{cn}' failed: "
                    f"{type(err).__name__}: {err}"
                )
                raise QueryParamValidationError(
                    msg="External HTTP validation could not be completed"
                )
        if resp.is_error:
            self.log.error(
                f"External HTTP validation for CN '{cn}' rejected with status "
                f"{resp.status_code}"
            )
            raise QueryParamValidationError(msg="External HTTP validation failed")

    async def run_script_check(
        self, cn: str, sans: List[str], config: CAScriptValidation
    ) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                config.script_path,
                env=script_environment(cn, sans),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as err:
            self.log.error(
                f"Validation script '{config.script_path}' could not be started: {err}"
            )
            raise QueryParamValidationError(
                msg="External script validation could not be executed"
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=config.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            self.log.error(
                f"Validation script '{config.script_path}' timed out after "
                f"{config.timeout_seconds}s for CN '{cn}'"
            )
            raise QueryParamValidationError(msg="External script validation timed out")
        if proc.returncode != 0:
            output = (
                stderr.decode(errors="replace").strip()
                or stdout.decode(errors="replace").strip()
            )
            self.log.error(
                f"Validation script '{config.script_path}' rejected CN '{cn}' "
                f"(exit {proc.returncode}): {output}"
            )
            raise QueryParamValidationError(msg="External script validation failed")
