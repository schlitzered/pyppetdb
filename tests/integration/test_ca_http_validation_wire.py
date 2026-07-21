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

"""Stage 1 wire tests: drive ``CAService._execute_http_validation`` against a
real local HTTP(S) server and assert that exactly the expected request arrives
(secret-resolved headers, {{cn}}/{{sans}} body, {cert_cn} url, and a real mTLS
handshake). No MongoDB required – the service is built with mocked cruds.
"""

import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from pyppetdb.ca.service import CAService
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation, CAHTTPHeader
from tests.integration._dummy_http import (
    CapturingServer,
    self_signed_cert,
    server_tls_context,
)


class CAHttpValidationWireTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, secret_map=None):
        config = MagicMock()
        config.ca.concurrentWorkers = 2
        crud_secrets = AsyncMock()
        crud_secrets.get_values = AsyncMock(return_value=secret_map or {})
        return CAService(
            log=MagicMock(),
            config=config,
            crud_authorities=AsyncMock(),
            crud_spaces=AsyncMock(),
            crud_certificates=AsyncMock(),
            crud_pyppetdb_nodes=MagicMock(),
            crud_secrets=crud_secrets,
        )

    async def test_plain_http_delivers_resolved_request(self):
        service = self._service(secret_map={"TOK": "abc123"})
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
            await service._execute_http_validation(
                cn="node1.example.com",
                sans=["a.example.com", "b.example.com"],
                config=config,
                ca_id="ca",
                space_id="sp",
            )

            self.assertEqual(len(server.captured), 1)
            req = server.captured[0]
            self.assertEqual(req["method"], "POST")
            # {cert_cn} substituted into the query string
            self.assertEqual(req["path"], "/validate?cn=node1.example.com")
            # $secrets[TOK] resolved into the header
            self.assertEqual(req["headers"]["Authorization"], "Bearer abc123")
            # {{cn}} / {{sans}} substituted into the JSON body
            self.assertEqual(
                json.loads(req["body"]),
                {
                    "node": "node1.example.com",
                    "sans": ["a.example.com", "b.example.com"],
                },
            )

    async def test_default_body_when_no_template(self):
        service = self._service()
        with CapturingServer() as server:
            config = CAHTTPValidation(
                url=f"http://127.0.0.1:{server.port}/v", method="POST"
            )
            await service._execute_http_validation(
                cn="n1", sans=["s1"], config=config, ca_id="ca", space_id="sp"
            )
            req = server.captured[0]
            self.assertEqual(json.loads(req["body"]), {"cn": "n1", "sans": ["s1"]})

    async def test_mtls_handshake_presents_client_cert(self):
        server_cert, server_key = self_signed_cert("server", san_ip="127.0.0.1")
        client_cert, client_key = self_signed_cert("client.example.com")
        # server trusts our client cert and requires one (real mTLS)
        tls_ctx = server_tls_context(
            server_cert, server_key, client_ca_pem=client_cert
        )
        service = self._service(secret_map={"CK": client_key})
        with CapturingServer(tls_ctx=tls_ctx) as server:
            config = CAHTTPValidation(
                url=f"https://127.0.0.1:{server.port}/mtls",
                method="GET",
                verify_ssl=True,
                ca_cert=server_cert,  # verify the server against its own cert
                client_cert=client_cert,
                client_key="$secrets[CK]",  # resolved from the secret store
            )
            await service._execute_http_validation(
                cn="node2", sans=["node2"], config=config, ca_id="ca", space_id="sp"
            )

            self.assertEqual(len(server.captured), 1)
            peercert = server.captured[0]["peercert"]
            self.assertIsNotNone(peercert, "client certificate was not presented")
            subject = dict(x[0] for x in peercert["subject"])
            self.assertEqual(subject["commonName"], "client.example.com")

    async def test_server_verification_rejects_untrusted_cert(self):
        # server presents cert A, but the check trusts a *different* CA -> the
        # client must refuse the connection (fail-closed).
        server_cert, server_key = self_signed_cert("server", san_ip="127.0.0.1")
        other_cert, _ = self_signed_cert("other", san_ip="127.0.0.1")
        tls_ctx = server_tls_context(server_cert, server_key)
        service = self._service()
        with CapturingServer(tls_ctx=tls_ctx) as server:
            config = CAHTTPValidation(
                url=f"https://127.0.0.1:{server.port}/v",
                method="GET",
                verify_ssl=True,
                ca_cert=other_cert,  # wrong trust anchor
            )
            with self.assertRaises(QueryParamValidationError):
                await service._execute_http_validation(
                    cn="n", sans=["n"], config=config, ca_id="ca", space_id="sp"
                )


if __name__ == "__main__":
    unittest.main()
