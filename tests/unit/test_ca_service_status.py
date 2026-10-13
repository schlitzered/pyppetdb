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

from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import MagicMock, AsyncMock
from pyppetdb.ca.signer import CASigners
from pyppetdb.ca.validation import CSRValidator
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_authorities import CAAuthorityGet, CAAuthorityPut
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.model.ca_certificates import CACertificateGetMulti
from pyppetdb.model.ca_validation import CAValidationConfig
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpacePut


def _multi(model, items):
    return model(result=items, meta={"result_size": len(items)})


class TestCAServiceStatusUpdate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = MagicMock()
        self.config = MagicMock()
        self.config.ca.concurrentWorkers = 2
        self.config.ca.certificateRequestTtlDays = 30
        self.crud_authorities = AsyncMock()
        self.crud_spaces = AsyncMock()
        self.crud_spaces.search.return_value = _multi(CASpaceGetMulti, [])
        self.crud_authorities.search.return_value = _multi(CAAuthorityGetMulti, [])
        self.crud_certificates = AsyncMock()
        self.crud_pyppetdb_nodes = MagicMock()
        self.crud_secrets = AsyncMock()
        executor = ThreadPoolExecutor(max_workers=1)
        self.service = CAService(
            log=self.log,
            config=self.config,
            crud_authorities=self.crud_authorities,
            crud_spaces=self.crud_spaces,
            crud_certificates=self.crud_certificates,
            signers=CASigners(
                crud_authorities=self.crud_authorities, executor=executor
            ),
            validator=CSRValidator(
                log=self.log, crud_secrets=self.crud_secrets
            ),
            executor=executor,
        )

    async def test_update_certificate_status_transition_requested_to_signed(self):
        # Mock finding a requested cert
        cert_req = CACertificateGet(
            id="123", status="requested", cn="node1", space_id="space1"
        )
        self.crud_certificates.get_active_by_cn.side_effect = [cert_req]

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
        self.crud_certificates.get_active_by_cn.return_value = cert_signed

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
        self.crud_certificates.get_active_by_cn.return_value = cert_signed

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
        self.crud_certificates.get_active_by_cn.side_effect = ResourceNotFound()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status(
                space_id="space1",
                cn="node1",
                payload=CACertificatePut(status="signed"),
                fields=[],
            )

    async def test_revoke_without_active_cert_raises_not_found(self):
        self.crud_certificates.get_active_by_cn.side_effect = ResourceNotFound()
        self.service.revoke_certificate = AsyncMock()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status(
                space_id="space1",
                cn="node1",
                payload=CACertificatePut(status="revoked"),
                fields=[],
            )
        self.service.revoke_certificate.assert_not_called()

    async def test_sign_without_active_cert_ignores_revoked_ones(self):
        self.crud_certificates.get_active_by_cn.side_effect = ResourceNotFound()
        self.service.process_requested_certificate = AsyncMock()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status(
                space_id="space1",
                cn="node1",
                payload=CACertificatePut(status="signed"),
                fields=[],
            )
        self.service.process_requested_certificate.assert_not_called()


class TestCAServiceClean(unittest.IsolatedAsyncioTestCase):
    setUp = TestCAServiceStatusUpdate.setUp

    async def test_unknown_node_is_a_success(self):
        self.crud_certificates.get_active_by_cn.side_effect = ResourceNotFound()
        self.service.revoke_certificate = AsyncMock()

        await self.service.clean_certificate(space_id="space1", cn="node1")

        self.crud_certificates.delete_requests.assert_called_once_with(
            space_id="space1", cn="node1"
        )
        self.service.revoke_certificate.assert_not_called()

    async def test_certificate_vanishing_during_the_revoke_is_a_success(self):
        self.crud_certificates.get_active_by_cn.return_value = CACertificateGet(
            id="123", status="signed", cn="node1", space_id="space1"
        )
        self.service.revoke_certificate = AsyncMock(side_effect=ResourceNotFound())

        await self.service.clean_certificate(space_id="space1", cn="node1")

    async def test_signed_certificate_is_revoked_and_requests_are_dropped(self):
        self.crud_certificates.get_active_by_cn.return_value = CACertificateGet(
            id="123", status="signed", cn="node1", space_id="space1"
        )
        self.service.revoke_certificate = AsyncMock()

        await self.service.clean_certificate(space_id="space1", cn="node1")

        self.crud_certificates.delete_requests.assert_called_once_with(
            space_id="space1", cn="node1"
        )
        self.service.revoke_certificate.assert_called_once_with(_id="123")

    async def test_a_request_submitted_meanwhile_is_left_alone(self):
        self.crud_certificates.get_active_by_cn.return_value = CACertificateGet(
            id="456", status="requested", cn="node1", space_id="space1"
        )
        self.service.revoke_certificate = AsyncMock()

        await self.service.clean_certificate(space_id="space1", cn="node1")

        self.service.revoke_certificate.assert_not_called()


class TestCAServiceRevokeRequest(unittest.IsolatedAsyncioTestCase):
    setUp = TestCAServiceStatusUpdate.setUp

    async def test_revoking_a_request_deletes_it(self):
        self.crud_certificates.delete_request.return_value = CACertificateGet(
            id="123", status="requested", cn="node1", space_id="space1"
        )
        seen = []
        self.service.add_revocation_listener(lambda serial: seen.append(serial))

        result = await self.service.revoke_certificate(_id="123")

        self.crud_certificates.delete_request.assert_called_once_with(_id="123")
        self.crud_certificates.revoke.assert_not_called()
        self.assertEqual(result.status, "revoked")
        self.assertIsNotNone(result.revocation_date)
        self.assertEqual(seen, [])

    async def test_revoking_a_signed_certificate_keeps_it(self):
        self.crud_certificates.delete_request.return_value = None
        self.crud_certificates.revoke.return_value = CACertificateGet(
            id="123", status="revoked", cn="node1", space_id="space1"
        )

        result = await self.service.revoke_certificate(_id="123")

        self.crud_certificates.revoke.assert_called_once()
        self.assertEqual(result.status, "revoked")


class TestCAServiceUpdateAuthority(unittest.IsolatedAsyncioTestCase):
    setUp = TestCAServiceStatusUpdate.setUp

    async def test_revoke_sets_revocation_date(self):
        ca = CAAuthorityGet(id="sub", status="revoked")
        self.crud_authorities.get.return_value = ca

        result = await self.service.update_authority(
            ca_id="sub", payload=CAAuthorityPut(status="revoked"), fields=[]
        )

        self.assertEqual(result, ca)
        kwargs = self.crud_authorities.revoke.call_args.kwargs
        self.assertEqual(kwargs["_id"], "sub")
        self.assertIsNotNone(kwargs["revocation_date"].tzinfo)
        self.crud_authorities.update.assert_not_called()

    async def test_revoking_again_keeps_the_first_date(self):
        self.crud_authorities.revoke.side_effect = ResourceNotFound()
        self.crud_authorities.get.return_value = CAAuthorityGet(
            id="sub", status="revoked"
        )

        await self.service.update_authority(
            ca_id="sub", payload=CAAuthorityPut(status="revoked"), fields=[]
        )

        self.crud_authorities.update.assert_not_called()

    async def test_revoking_unknown_authority_raises_not_found(self):
        self.crud_authorities.revoke.side_effect = ResourceNotFound()
        self.crud_authorities.get.side_effect = ResourceNotFound()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_authority(
                ca_id="nope", payload=CAAuthorityPut(status="revoked"), fields=[]
            )

    async def test_validation_config_update_does_not_revoke(self):
        payload = CAAuthorityPut(validation_config=CAValidationConfig(max_san_count=3))

        await self.service.update_authority(ca_id="sub", payload=payload, fields=[])

        self.crud_authorities.revoke.assert_not_called()
        self.crud_authorities.update.assert_called_once()
        self.assertNotIn(
            "status",
            self.crud_authorities.update.call_args.kwargs["payload"].model_dump(
                exclude_unset=True
            ),
        )

    async def test_revoke_rejected_while_spaces_use_the_authority(self):
        self.crud_spaces.search.return_value = _multi(
            CASpaceGetMulti, [CASpaceGet(id="space-b"), CASpaceGet(id="space-a")]
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.update_authority(
                ca_id="sub.1", payload=CAAuthorityPut(status="revoked"), fields=[]
            )

        self.assertEqual(
            ctx.exception.detail,
            "CA Authority 'sub.1' is still used by spaces: space-a, space-b",
        )
        self.crud_spaces.search.assert_awaited_with(ca_id="^sub\\.1$", fields=["id"])
        self.crud_authorities.revoke.assert_not_called()

    async def test_revoke_rejected_while_active_sub_authorities_exist(self):
        self.crud_authorities.search.return_value = _multi(
            CAAuthorityGetMulti, [CAAuthorityGet(id="sub2"), CAAuthorityGet(id="sub1")]
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.update_authority(
                ca_id="root", payload=CAAuthorityPut(status="revoked"), fields=[]
            )

        self.assertEqual(
            ctx.exception.detail,
            "CA Authority 'root' is still the parent of active authorities: sub1, sub2",
        )
        self.crud_authorities.search.assert_awaited_with(
            parent_id="^root$", status="active", fields=["id"]
        )
        self.crud_authorities.revoke.assert_not_called()

    async def test_validation_update_skips_the_usage_check(self):
        self.crud_spaces.search.return_value = _multi(
            CASpaceGetMulti, [CASpaceGet(id="space-a")]
        )
        self.crud_authorities.update.return_value = CAAuthorityGet(id="sub")

        await self.service.update_authority(
            ca_id="sub", payload=CAAuthorityPut(validation_config={}), fields=[]
        )

        self.crud_spaces.search.assert_not_called()
        self.crud_authorities.revoke.assert_not_called()

    async def test_space_cannot_be_created_on_a_revoked_authority(self):
        self.crud_authorities.get.return_value = CAAuthorityGet(
            id="old", status="revoked"
        )

        with self.assertRaises(QueryParamValidationError):
            await self.service.create_space(
                _id="s1", payload=CASpacePost(ca_id="old"), fields=[]
            )

        self.crud_spaces.create.assert_not_called()

    async def test_space_cannot_be_moved_to_a_revoked_authority(self):
        self.crud_authorities.get.return_value = CAAuthorityGet(
            id="old", status="revoked"
        )

        with self.assertRaises(QueryParamValidationError):
            await self.service.update_space(
                _id="s1", payload=CASpacePut(ca_id="old"), fields=[]
            )

        self.crud_spaces.update.assert_not_called()

    async def test_space_update_without_ca_change_skips_the_check(self):
        self.crud_spaces.update.return_value = MagicMock()

        await self.service.update_space(
            _id="s1", payload=CASpacePut(description="x"), fields=[]
        )

        self.crud_authorities.get.assert_not_called()

    async def test_delete_rejected_while_spaces_use_the_authority(self):
        self.crud_spaces.search.return_value = _multi(
            CASpaceGetMulti, [CASpaceGet(id="space-b"), CASpaceGet(id="space-a")]
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.delete_authority("old")

        self.assertEqual(
            ctx.exception.detail,
            "CA Authority 'old' is still used by spaces: space-a, space-b, cannot delete",
        )
        self.crud_authorities.delete.assert_not_called()

    async def test_delete_space_rejected_while_it_holds_certificates(self):
        self.crud_certificates.search.return_value = CACertificateGetMulti(
            result=[], meta={"result_size": 3}
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.delete_space("s1")

        self.assertEqual(
            ctx.exception.detail, "Space 's1' still contains 3 certificates, cannot delete"
        )
        self.crud_certificates.search.assert_awaited_once_with(
            space_id="s1", fields=["id"], limit=1
        )
        self.crud_spaces.delete.assert_not_called()

    async def test_delete_empty_space(self):
        self.crud_certificates.search.return_value = _multi(CACertificateGetMulti, [])

        await self.service.delete_space("s1")

        self.crud_spaces.delete.assert_awaited_once_with(_id="s1")

    async def test_delete_authority_lists_sub_authorities_of_any_status(self):
        self.crud_authorities.search.return_value = _multi(
            CAAuthorityGetMulti,
            [CAAuthorityGet(id="sub2", status="revoked"), CAAuthorityGet(id="sub1")],
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.delete_authority("root")

        self.assertEqual(
            ctx.exception.detail,
            "CA Authority 'root' is still the parent of authorities: sub1, sub2, cannot delete",
        )
        self.crud_authorities.search.assert_awaited_with(
            parent_id="^root$", status=None, fields=["id"]
        )
        self.crud_authorities.delete.assert_not_called()
