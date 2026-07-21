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

from pyppetdb.ca.service import CAService
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation, CAHTTPHeader


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


class TestCAServiceSecretResolution(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _captured.clear()
        self.config = MagicMock()
        self.config.ca.concurrentWorkers = 2
        self.crud_secrets = AsyncMock()
        self.service = CAService(
            log=MagicMock(),
            config=self.config,
            crud_authorities=AsyncMock(),
            crud_spaces=AsyncMock(),
            crud_certificates=AsyncMock(),
            crud_pyppetdb_nodes=MagicMock(),
            crud_secrets=self.crud_secrets,
        )

    @patch("pyppetdb.ca.service.httpx.AsyncClient", _FakeClient)
    async def test_resolves_secret_into_header(self):
        self.crud_secrets.get_values = AsyncMock(return_value={"TOK": "abc123"})
        check = CAHTTPValidation(
            url="https://validate.example.com",
            method="POST",
            headers=[
                CAHTTPHeader(name="Authorization", value="Bearer $secrets[TOK]")
            ],
        )
        await self.service._execute_http_validation(
            cn="node1", sans=["node1"], config=check, ca_id="ca", space_id="sp"
        )
        self.crud_secrets.get_values.assert_awaited_once()
        self.assertEqual(
            _captured["request"]["headers"]["Authorization"], "Bearer abc123"
        )

    @patch("pyppetdb.ca.service.httpx.AsyncClient", _FakeClient)
    async def test_unknown_secret_fails_closed(self):
        self.crud_secrets.get_values = AsyncMock(return_value={})
        check = CAHTTPValidation(
            url="https://validate.example.com",
            headers=[
                CAHTTPHeader(name="Authorization", value="Bearer $secrets[MISSING]")
            ],
        )
        with self.assertRaises(QueryParamValidationError):
            await self.service._execute_http_validation(
                cn="node1", sans=["node1"], config=check, ca_id="ca", space_id="sp"
            )
        self.assertNotIn("request", _captured)

    @patch("pyppetdb.ca.service.httpx.AsyncClient", _FakeClient)
    async def test_no_references_skips_secret_lookup(self):
        self.crud_secrets.get_values = AsyncMock(return_value={})
        check = CAHTTPValidation(
            url="https://validate.example.com",
            headers=[CAHTTPHeader(name="X-Static", value="plain")],
        )
        await self.service._execute_http_validation(
            cn="node1", sans=["node1"], config=check, ca_id="ca", space_id="sp"
        )
        self.crud_secrets.get_values.assert_not_awaited()
        self.assertEqual(_captured["request"]["headers"]["X-Static"], "plain")


if __name__ == "__main__":
    unittest.main()
