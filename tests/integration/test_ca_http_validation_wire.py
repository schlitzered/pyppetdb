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

import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from pyppetdb.ca.validation import CSRValidator
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation, CAHTTPHeader
from tests.integration._dummy_http import (
    CapturingServer,
    self_signed_cert,
    server_tls_context,
)


class CAHttpValidationWireTests(unittest.IsolatedAsyncioTestCase):
    def _validator(self):
        return CSRValidator(log=MagicMock(), crud_secrets=AsyncMock())

    async def test_plain_http_delivers_resolved_request(self):
        validator = self._validator()
        secrets = {"TOK": "abc123"}
        with CapturingServer() as server:
            config = CAHTTPValidation(
                url=f"http://127.0.0.1:{server.port}/validate?cn={{cert_cn}}",
                method="POST",
                headers=[
                    CAHTTPHeader(
                        name="Authorization", value="Bearer $secrets[TOK]"
                    )
                ],
                body_template='{"node":"{{cn}}","sans":{{sans}}}',
            )
            await validator.run_http_check(
                cn="node1.example.com",
                sans=["a.example.com", "b.example.com"],
                config=config,
                ca_id="ca",
                space_id="sp",
                secrets=secrets,
            )

            self.assertEqual(len(server.captured), 1)
            req = server.captured[0]
            self.assertEqual(req["method"], "POST")
            self.assertEqual(req["path"], "/validate?cn=node1.example.com")
            self.assertEqual(req["headers"]["Authorization"], "Bearer abc123")
            self.assertEqual(
                json.loads(req["body"]),
                {
                    "node": "node1.example.com",
                    "sans": ["a.example.com", "b.example.com"],
                },
            )

    async def test_default_body_when_no_template(self):
        validator = self._validator()
        secrets = {}
        with CapturingServer() as server:
            config = CAHTTPValidation(
                url=f"http://127.0.0.1:{server.port}/v", method="POST"
            )
            await validator.run_http_check(
                cn="n1", sans=["s1"], config=config, ca_id="ca", space_id="sp",
                secrets=secrets,
            )
            req = server.captured[0]
            self.assertEqual(json.loads(req["body"]), {"cn": "n1", "sans": ["s1"]})

    async def test_mtls_handshake_presents_client_cert(self):
        server_cert, server_key = self_signed_cert("server", san_ip="127.0.0.1")
        client_cert, client_key = self_signed_cert("client.example.com")
        tls_ctx = server_tls_context(
            server_cert, server_key, client_ca_pem=client_cert
        )
        validator = self._validator()
        secrets = {"CK": client_key}
        with CapturingServer(tls_ctx=tls_ctx) as server:
            config = CAHTTPValidation(
                url=f"https://127.0.0.1:{server.port}/mtls",
                method="GET",
                verify_ssl=True,
                ca_cert=server_cert,
                client_cert=client_cert,
                client_key="$secrets[CK]",
            )
            await validator.run_http_check(
                cn="node2", sans=["node2"], config=config, ca_id="ca", space_id="sp",
                secrets=secrets,
            )

            self.assertEqual(len(server.captured), 1)
            peercert = server.captured[0]["peercert"]
            self.assertIsNotNone(peercert, "client certificate was not presented")
            subject = dict(x[0] for x in peercert["subject"])
            self.assertEqual(subject["commonName"], "client.example.com")

    async def test_server_verification_rejects_untrusted_cert(self):
        server_cert, server_key = self_signed_cert("server", san_ip="127.0.0.1")
        other_cert, _ = self_signed_cert("other", san_ip="127.0.0.1")
        tls_ctx = server_tls_context(server_cert, server_key)
        validator = self._validator()
        secrets = {}
        with CapturingServer(tls_ctx=tls_ctx) as server:
            config = CAHTTPValidation(
                url=f"https://127.0.0.1:{server.port}/v",
                method="GET",
                verify_ssl=True,
                ca_cert=other_cert,
            )
            with self.assertRaises(QueryParamValidationError):
                await validator.run_http_check(
                    cn="n", sans=["n"], config=config, ca_id="ca", space_id="sp",
                    secrets=secrets,
                )


if __name__ == "__main__":
    unittest.main()
