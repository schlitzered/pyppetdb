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
from unittest.mock import MagicMock, AsyncMock
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.errors import ResourceNotFound


class TestCAServiceStatusUpdate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = MagicMock()
        self.config = MagicMock()
        self.config.ca.concurrentWorkers = 2
        self.crud_authorities = AsyncMock()
        self.crud_spaces = AsyncMock()
        self.crud_certificates = AsyncMock()
        self.crud_pyppetdb_nodes = MagicMock()
        self.crud_secrets = AsyncMock()
        self.service = CAService(
            log=self.log,
            config=self.config,
            crud_authorities=self.crud_authorities,
            crud_spaces=self.crud_spaces,
            crud_certificates=self.crud_certificates,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
            crud_secrets=self.crud_secrets,
        )

    async def test_update_certificate_status_transition_requested_to_signed(self):
        # Mock finding a requested cert
        cert_req = CACertificateGet(
            id="123", status="requested", cn="node1", space_id="space1"
        )
        self.crud_certificates.get_by_cn.side_effect = [cert_req]

        # Mock processing the request
        self.service.process_requested_certificate = AsyncMock(return_value=cert_req)

        result = await self.service.update_certificate_status(
            space_id="space1",
            cn="node1",
            payload=CACertificatePut(status="signed"),
            fields=[],
        )

        self.assertEqual(result, cert_req)
        self.service.process_requested_certificate.assert_called_once_with(_id="123")

    async def test_update_certificate_status_already_signed(self):
        # Mock finding a signed cert in one call
        cert_signed = CACertificateGet(
            id="123", status="signed", cn="node1", space_id="space1"
        )
        self.crud_certificates.get_by_cn.return_value = cert_signed

        # Mock processing should NOT be called
        self.service.process_requested_certificate = AsyncMock()

        result = await self.service.update_certificate_status(
            space_id="space1",
            cn="node1",
            payload=CACertificatePut(status="signed"),
            fields=[],
        )

        self.assertEqual(result, cert_signed)
        self.service.process_requested_certificate.assert_not_called()

    async def test_update_certificate_status_revoke_signed(self):
        # Mock finding a signed cert in one call
        cert_signed = CACertificateGet(
            id="123", status="signed", cn="node1", space_id="space1"
        )
        self.crud_certificates.get_by_cn.return_value = cert_signed

        # Mock revocation
        self.service.revoke_certificate = AsyncMock(return_value=cert_signed)

        result = await self.service.update_certificate_status(
            space_id="space1",
            cn="node1",
            payload=CACertificatePut(status="revoked"),
            fields=[],
        )

        self.assertEqual(result, cert_signed)
        self.service.revoke_certificate.assert_called_once_with(_id="123")

    async def test_update_certificate_status_not_found(self):
        # Mock finding nothing in one call
        self.crud_certificates.get_by_cn.side_effect = ResourceNotFound()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status(
                space_id="space1",
                cn="node1",
                payload=CACertificatePut(status="signed"),
                fields=[],
            )
