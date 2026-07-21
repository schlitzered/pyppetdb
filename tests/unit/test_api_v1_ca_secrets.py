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

from pyppetdb.authorize import (
    PERM_CA_GET,
    PERM_CA_SECRETS_CREATE,
    PERM_CA_SECRETS_UPDATE,
    PERM_CA_SECRETS_DELETE,
)
from pyppetdb.controller.api.v1.ca_secrets import ControllerApiV1CASecrets
from pyppetdb.errors import QueryParamValidationError, ResourceInUse
from pyppetdb.model.ca_secrets import CASecretPost, CASecretPut


class TestApiV1CASecretsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.authorize = MagicMock()
        self.authorize.require_perm = AsyncMock()
        self.crud_secrets = MagicMock()
        self.crud_authorities = MagicMock()
        self.crud_spaces = MagicMock()
        self.controller = ControllerApiV1CASecrets(
            log=self.log,
            authorize=self.authorize,
            crud_secrets=self.crud_secrets,
            crud_authorities=self.crud_authorities,
            crud_spaces=self.crud_spaces,
        )

    async def test_create_requires_perm_and_delegates(self):
        self.crud_secrets.create = AsyncMock(return_value={"id": "TOK"})
        request = MagicMock()
        await self.controller.create(
            request=request,
            secret_id="TOK",
            data=CASecretPost(secret="s"),
            fields=set(),
        )
        self.authorize.require_perm.assert_called_once_with(
            request=request, permission=PERM_CA_SECRETS_CREATE
        )
        self.crud_secrets.create.assert_called_once()
        self.assertEqual(self.crud_secrets.create.call_args[1]["_id"], "TOK")

    async def test_create_rejects_invalid_id(self):
        self.crud_secrets.create = AsyncMock()
        with self.assertRaises(QueryParamValidationError):
            await self.controller.create(
                request=MagicMock(),
                secret_id="bad id!",
                data=CASecretPost(secret="s"),
                fields=set(),
            )
        self.crud_secrets.create.assert_not_called()

    async def test_update_requires_perm(self):
        self.crud_secrets.update = AsyncMock(return_value={"id": "TOK"})
        request = MagicMock()
        await self.controller.update(
            request=request,
            secret_id="TOK",
            data=CASecretPut(secret="s2"),
            fields=set(),
        )
        self.authorize.require_perm.assert_called_once_with(
            request=request, permission=PERM_CA_SECRETS_UPDATE
        )

    async def test_get_uses_ca_get_perm(self):
        self.crud_secrets.get = AsyncMock(return_value={"id": "TOK"})
        request = MagicMock()
        await self.controller.get(request=request, secret_id="TOK", fields=set())
        self.authorize.require_perm.assert_called_once_with(
            request=request, permission=PERM_CA_GET
        )

    async def test_delete_blocked_when_referenced(self):
        self.crud_secrets.resource_exists = AsyncMock(return_value="TOK")
        self.crud_secrets.delete = AsyncMock()
        self.crud_authorities.find_referencing_ids = AsyncMock(return_value=["my-ca"])
        self.crud_spaces.find_referencing_ids = AsyncMock(return_value=["my-space"])

        with self.assertRaises(ResourceInUse) as ctx:
            await self.controller.delete(request=MagicMock(), secret_id="TOK")

        detail = str(ctx.exception.detail)
        self.assertIn("ca_authority:my-ca", detail)
        self.assertIn("ca_space:my-space", detail)
        self.crud_secrets.delete.assert_not_called()

    async def test_delete_allowed_when_unreferenced(self):
        self.crud_secrets.resource_exists = AsyncMock(return_value="TOK")
        self.crud_secrets.delete = AsyncMock()
        self.crud_authorities.find_referencing_ids = AsyncMock(return_value=[])
        self.crud_spaces.find_referencing_ids = AsyncMock(return_value=[])
        request = MagicMock()

        await self.controller.delete(request=request, secret_id="TOK")

        self.authorize.require_perm.assert_called_once_with(
            request=request, permission=PERM_CA_SECRETS_DELETE
        )
        self.crud_secrets.delete.assert_called_once_with(_id="TOK")


if __name__ == "__main__":
    unittest.main()
