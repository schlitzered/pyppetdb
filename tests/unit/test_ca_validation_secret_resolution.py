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

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

from cryptography import x509

from pyppetdb.ca import crypto
from pyppetdb.ca.validation import CSRValidator
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPHeader
from pyppetdb.model.ca_validation import CAHTTPValidation
from pyppetdb.model.ca_validation import CASANValidation
from pyppetdb.model.ca_validation import CAValidationConfig


def _csr(cn):
    csr_pem, _ = crypto.generate_csr(cn)
    return csr_pem, x509.load_pem_x509_csr(csr_pem)


_captured: dict = {}


class _FakeClient:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, **kwargs):
        _captured["request"] = kwargs
        return SimpleNamespace(is_error=False, status_code=200)


def _http_config(*headers):
    return CAValidationConfig(
        san_validation=CASANValidation(
            http_checks=[
                CAHTTPValidation(
                    url="https://validate.example.com",
                    headers=[CAHTTPHeader(name=f"H{i}", value=v) for i, v in enumerate(headers)],
                )
            ]
        )
    )


class TestCSRValidatorSecretResolution(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _captured.clear()
        self.crud_secrets = AsyncMock()
        self.crud_secrets.get_values = AsyncMock(return_value={"TOK": "abc123"})
        self.validator = CSRValidator(log=MagicMock(), crud_secrets=self.crud_secrets)
        _, self.csr = _csr("node1")

    @patch("pyppetdb.ca.validation.httpx.AsyncClient", _FakeClient)
    async def test_resolves_secret_from_passed_map(self):
        check = CAHTTPValidation(
            url="https://validate.example.com",
            headers=[CAHTTPHeader(name="Authorization", value="Bearer $secrets[TOK]")],
        )

        await self.validator.run_http_check(
            cn="node1", sans=[], config=check, ca_id="ca", space_id="sp",
            secrets={"TOK": "abc123"},
        )

        self.assertEqual(_captured["request"]["headers"]["Authorization"], "Bearer abc123")
        self.crud_secrets.get_values.assert_not_awaited()

    @patch("pyppetdb.ca.validation.httpx.AsyncClient", _FakeClient)
    async def test_reference_missing_from_map_fails_closed(self):
        check = CAHTTPValidation(
            url="https://validate.example.com",
            headers=[CAHTTPHeader(name="Authorization", value="Bearer $secrets[MISSING]")],
        )

        with self.assertRaises(QueryParamValidationError):
            await self.validator.run_http_check(
                cn="node1", sans=[], config=check, ca_id="ca", space_id="sp",
                secrets={"TOK": "abc123"},
            )

        self.assertNotIn("request", _captured)

    @patch("pyppetdb.ca.validation.httpx.AsyncClient", _FakeClient)
    async def test_validate_loads_stored_refs_once_for_all_checks(self):
        ca_config = _http_config("$secrets[TOK]")
        space_config = _http_config("x $secrets[TOK]")

        await self.validator.validate(
            csr=self.csr, cn="node1", ca_config=ca_config, space_config=space_config,
            ca_id="ca", space_id="sp", secret_refs=["TOK", "TOK"],
        )

        self.crud_secrets.get_values.assert_awaited_once_with({"TOK"})
        self.assertEqual(_captured["request"]["headers"]["H0"], "x abc123")

    @patch("pyppetdb.ca.validation.httpx.AsyncClient", _FakeClient)
    async def test_validate_without_stored_refs_fails_closed(self):
        with self.assertRaises(QueryParamValidationError):
            await self.validator.validate(
                csr=self.csr, cn="node1", ca_config=_http_config("$secrets[TOK]"),
                space_config=CAValidationConfig(), ca_id="ca", space_id="sp",
            )

        self.crud_secrets.get_values.assert_not_awaited()
        self.assertNotIn("request", _captured)

    async def test_validate_skips_secret_lookup_without_http_checks(self):
        await self.validator.validate(
            csr=self.csr, cn="node1", ca_config=CAValidationConfig(),
            space_config=CAValidationConfig(), ca_id="ca", space_id="sp",
            secret_refs=["TOK"],
        )

        self.crud_secrets.get_values.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
