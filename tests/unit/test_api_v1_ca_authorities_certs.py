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

from pyppetdb.authorize import PERM_CA_GET, PERM_CA_AUTHORITIES_CERTS_UPDATE
from pyppetdb.controller.api.v1.ca_authorities_certs import (
    ControllerApiV1CAAuthoritiesCerts,
)
from pyppetdb.errors import ResourceNotFound


def _multi(certs):
    multi = MagicMock()
    multi.result = list(certs)
    return multi


class TestApiV1CAAuthoritiesCertsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_certificates = MagicMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1CAAuthoritiesCerts(
            log=self.log,
            authorize=self.mock_authorize,
            crud_authorities=self.mock_crud_authorities,
            crud_certificates=self.mock_crud_certificates,
            ca_service=self.mock_ca_service,
        )

    # ----- search -----
    async def test_search_without_ca_fields_no_populate(self):
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([]))
        self.controller._populate_ca_info = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request, ca_id="ca1", fields={"id", "cn"}
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_CA_GET
        )
        _, kwargs = self.mock_crud_certificates.search.call_args
        self.assertNotIn("ca_id", kwargs["fields"])
        self.controller._populate_ca_info.assert_not_called()

    async def test_search_with_ca_field_appends_ca_id_and_populates(self):
        cert = MagicMock()
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([cert]))
        self.controller._populate_ca_info = AsyncMock()

        await self.controller.search(
            request=MagicMock(), ca_id="ca1", fields={"id", "ca"}
        )

        _, kwargs = self.mock_crud_certificates.search.call_args
        self.assertIn("ca_id", kwargs["fields"])
        self.controller._populate_ca_info.assert_called_once_with(cert)

    # ----- get -----
    async def test_get_success(self):
        cert = MagicMock()
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([cert]))
        self.controller._populate_ca_info = AsyncMock()

        result = await self.controller.get(
            request=MagicMock(), ca_id="ca1", cert_id="cert1", fields={"id"}
        )

        self.assertIs(result, cert)
        _, kwargs = self.mock_crud_certificates.search.call_args
        self.assertEqual(kwargs["_id"], "^cert1$")
        self.assertEqual(kwargs["ca_id"], "ca1")
        self.assertEqual(kwargs["limit"], 1)

    async def test_get_with_ca_field_populates(self):
        cert = MagicMock()
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([cert]))
        self.controller._populate_ca_info = AsyncMock()

        await self.controller.get(
            request=MagicMock(), ca_id="ca1", cert_id="cert1", fields={"ca_chain"}
        )

        _, kwargs = self.mock_crud_certificates.search.call_args
        self.assertIn("ca_id", kwargs["fields"])
        self.controller._populate_ca_info.assert_called_once_with(cert)

    async def test_get_not_found_raises_404(self):
        # empty search result must translate into a clean 404 ResourceNotFound
        self.mock_crud_certificates.search = AsyncMock(return_value=_multi([]))

        with self.assertRaises(ResourceNotFound) as ctx:
            await self.controller.get(
                request=MagicMock(), ca_id="ca1", cert_id="missing", fields={"id"}
            )
        self.assertEqual(ctx.exception.status_code, 404)

    # ----- update -----
    async def test_update_revokes_via_ca_service(self):
        cert = MagicMock()
        self.mock_ca_service.update_certificate_status_by_ca = AsyncMock(
            return_value=cert
        )
        self.controller._populate_ca_info = AsyncMock()

        data = MagicMock()
        mock_request = MagicMock()
        result = await self.controller.update(
            request=mock_request,
            ca_id="ca1",
            cert_id="cert1",
            data=data,
            fields={"id"},
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_AUTHORITIES_CERTS_UPDATE.format(ca_id="ca1"),
        )
        self.mock_ca_service.update_certificate_status_by_ca.assert_called_once()
        args, kwargs = self.mock_ca_service.update_certificate_status_by_ca.call_args
        self.assertEqual(args[0], "ca1")
        self.assertEqual(args[1], "cert1")
        self.assertIs(result, cert)
        self.controller._populate_ca_info.assert_not_called()

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

        # must not raise even if the CA lookup fails
        result = await self.controller._populate_ca_info(cert)
        self.assertIs(result, cert)


if __name__ == "__main__":
    unittest.main()
