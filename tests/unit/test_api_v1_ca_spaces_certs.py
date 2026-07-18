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
import unittest
from unittest.mock import MagicMock, AsyncMock

from pyppetdb.authorize import PERM_CA_GET, PERM_CA_SPACES_CERTS_UPDATE
from pyppetdb.controller.api.v1.ca_spaces_certs import ControllerApiV1CASpacesCerts
from pyppetdb.errors import ResourceNotFound


def _multi(certs):
    multi = MagicMock()
    multi.result = list(certs)
    return multi


class TestApiV1CASpacesCertsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_certificates = MagicMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_spaces = MagicMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1CASpacesCerts(
            log=self.log,
            authorize=self.mock_authorize,
            crud_certificates=self.mock_crud_certificates,
            crud_authorities=self.mock_crud_authorities,
            crud_spaces=self.mock_crud_spaces,
            ca_service=self.mock_ca_service,
        )

    # ----- search -----
    async def test_search_with_ca_field_appends_ca_id_and_populates(self):
        cert = MagicMock()
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([cert]))
        self.controller._populate_ca_info = AsyncMock()

        await self.controller.search(
            request=MagicMock(), space_id="space1", fields={"id", "ca"}
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=unittest.mock.ANY, permission=PERM_CA_GET
        )
        _, kwargs = self.mock_crud_certificates.search.call_args
        self.assertIn("ca_id", kwargs["fields"])
        self.assertEqual(kwargs["space_id"], "space1")
        self.controller._populate_ca_info.assert_called_once_with(cert)

    # ----- get -----
    async def test_get_success(self):
        cert = MagicMock()
        cert.space_id = "space1"
        self.mock_crud_certificates.get = AsyncMock(return_value=cert)

        result = await self.controller.get(
            request=MagicMock(), space_id="space1", cert_id="cert1", fields={"id"}
        )
        self.assertIs(result, cert)

    async def test_get_not_found_raises_404(self):
        self.mock_crud_certificates.get = AsyncMock(side_effect=ResourceNotFound())

        with self.assertRaises(ResourceNotFound) as ctx:
            await self.controller.get(
                request=MagicMock(),
                space_id="space1",
                cert_id="missing",
                fields={"id"},
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_space_mismatch_raises_404(self):
        cert = MagicMock()
        cert.space_id = "other-space"
        self.mock_crud_certificates.get = AsyncMock(return_value=cert)

        with self.assertRaises(ResourceNotFound) as ctx:
            await self.controller.get(
                request=MagicMock(),
                space_id="space1",
                cert_id="cert1",
                fields={"id"},
            )
        self.assertEqual(ctx.exception.status_code, 404)

    # ----- update -----
    async def test_update_signed_uses_update_certificate_status(self):
        cert_doc = MagicMock()
        cert_doc.space_id = "space1"
        cert_doc.cn = "node.example.com"
        cert_doc.ca_id = "ca1"
        self.mock_crud_certificates.get = AsyncMock(return_value=cert_doc)

        signed_cert = MagicMock()
        self.mock_ca_service.update_certificate_status = AsyncMock(
            return_value=signed_cert
        )

        data = MagicMock()
        data.status = "signed"
        mock_request = MagicMock()

        result = await self.controller.update(
            request=mock_request,
            space_id="space1",
            cert_id="cert1",
            data=data,
            fields={"id"},
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_SPACES_CERTS_UPDATE.format(space_id="space1"),
        )
        self.mock_ca_service.update_certificate_status.assert_called_once()
        args, _ = self.mock_ca_service.update_certificate_status.call_args
        self.assertEqual(args[0], "space1")
        self.assertEqual(args[1], "node.example.com")
        self.assertIs(result, signed_cert)

    async def test_update_revoked_uses_update_certificate_status_by_ca(self):
        cert_doc = MagicMock()
        cert_doc.space_id = "space1"
        cert_doc.ca_id = "ca1"
        self.mock_crud_certificates.get = AsyncMock(return_value=cert_doc)

        revoked_cert = MagicMock()
        self.mock_ca_service.update_certificate_status_by_ca = AsyncMock(
            return_value=revoked_cert
        )

        data = MagicMock()
        data.status = "revoked"

        result = await self.controller.update(
            request=MagicMock(),
            space_id="space1",
            cert_id="cert1",
            data=data,
            fields={"id"},
        )

        self.mock_ca_service.update_certificate_status_by_ca.assert_called_once()
        args, _ = self.mock_ca_service.update_certificate_status_by_ca.call_args
        self.assertEqual(args[0], "ca1")
        self.assertEqual(args[1], "cert1")
        self.assertIs(result, revoked_cert)

    async def test_update_space_mismatch_raises_404(self):
        cert_doc = MagicMock()
        cert_doc.space_id = "other-space"
        self.mock_crud_certificates.get = AsyncMock(return_value=cert_doc)

        data = MagicMock()
        data.status = "signed"

        with self.assertRaises(ResourceNotFound) as ctx:
            await self.controller.update(
                request=MagicMock(),
                space_id="space1",
                cert_id="cert1",
                data=data,
                fields={"id"},
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_update_not_found_raises_404(self):
        self.mock_crud_certificates.get = AsyncMock(side_effect=ResourceNotFound())

        data = MagicMock()
        data.status = "signed"

        with self.assertRaises(ResourceNotFound) as ctx:
            await self.controller.update(
                request=MagicMock(),
                space_id="space1",
                cert_id="missing",
                data=data,
                fields={"id"},
            )
        self.assertEqual(ctx.exception.status_code, 404)

    # ----- _populate_ca_info -----
    async def test_populate_ca_info_sets_fields(self):
        cert = MagicMock()
        cert.ca_id = "ca1"
        ca = MagicMock()
        ca.certificate = "CA-CERT"
        ca.chain = "CA-CHAIN"
        self.mock_crud_authorities.get = AsyncMock(return_value=ca)

        result = await self.controller._populate_ca_info(cert)
        self.assertEqual(result.ca, "CA-CERT")
        self.assertEqual(result.ca_chain, "CA-CHAIN")

    async def test_populate_ca_info_swallows_errors(self):
        cert = MagicMock()
        cert.ca_id = "ca1"
        self.mock_crud_authorities.get = AsyncMock(side_effect=Exception("boom"))
        result = await self.controller._populate_ca_info(cert)
        self.assertIs(result, cert)


if __name__ == "__main__":
    unittest.main()
