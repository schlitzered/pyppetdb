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
from unittest.mock import AsyncMock

from pyppetdb.ca.config_validation import validate_secret_references
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
    CAHTTPHeader,
)


def _config(check):
    return CAValidationConfig(san_validation=CASANValidation(http_checks=[check]))


class TestValidateSecretReferences(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.crud_secrets = AsyncMock()

    async def test_valid_references_pass(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value={"H", "P"})
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                basic_auth_enabled=True,
                password="$secrets[P]",
                headers=[CAHTTPHeader(name="Authorization", value="$secrets[H]")],
            )
        )
        await validate_secret_references(config, self.crud_secrets)
        self.crud_secrets.existing_ids.assert_awaited_once()

    async def test_unknown_reference_rejected(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value=set())
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                headers=[CAHTTPHeader(name="Authorization", value="$secrets[NOPE]")],
            )
        )
        with self.assertRaises(QueryParamValidationError) as ctx:
            await validate_secret_references(config, self.crud_secrets)
        self.assertIn("NOPE", str(ctx.exception.detail))

    async def test_url_reference_rejected(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value=set())
        config = _config(
            CAHTTPValidation(url="https://host/$secrets[URLSECRET]")
        )
        with self.assertRaises(QueryParamValidationError) as ctx:
            await validate_secret_references(config, self.crud_secrets)
        self.assertIn("url", str(ctx.exception.detail).lower())
        self.crud_secrets.existing_ids.assert_not_awaited()

    async def test_literal_password_rejected(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value=set())
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                basic_auth_enabled=True,
                password="topsecret",  # literal, not a reference
            )
        )
        with self.assertRaises(QueryParamValidationError) as ctx:
            await validate_secret_references(config, self.crud_secrets)
        self.assertIn("password", str(ctx.exception.detail).lower())

    async def test_referenced_password_allowed(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value={"P"})
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                basic_auth_enabled=True,
                password="$secrets[P]",
            )
        )
        await validate_secret_references(config, self.crud_secrets)

    async def test_literal_client_key_rejected(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value=set())
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                client_key="-----BEGIN PRIVATE KEY-----\ninline\n-----END PRIVATE KEY-----",
            )
        )
        with self.assertRaises(QueryParamValidationError) as ctx:
            await validate_secret_references(config, self.crud_secrets)
        self.assertIn("client_key", str(ctx.exception.detail).lower())

    async def test_referenced_client_key_allowed(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value={"K"})
        config = _config(
            CAHTTPValidation(
                url="https://validate.example.com",
                client_key="$secrets[K]",
            )
        )
        await validate_secret_references(config, self.crud_secrets)

    async def test_empty_config_noop(self):
        self.crud_secrets.existing_ids = AsyncMock(return_value=set())
        await validate_secret_references(CAValidationConfig(), self.crud_secrets)
        self.crud_secrets.existing_ids.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
