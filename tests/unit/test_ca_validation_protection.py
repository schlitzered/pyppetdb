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
from unittest.mock import MagicMock
from pyppetdb.ca.validation_protector import CAValidationProtector
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
    CAHTTPHeader,
)
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector


class TestCAValidationProtection(unittest.TestCase):
    def setUp(self):
        self.protector = MagicMock(spec=NodesDataProtector)
        self.protector.encrypt_string.side_effect = lambda x: f"enc_{x}"
        self.protector.decrypt_string.side_effect = lambda x: x.replace("enc_", "")
        self.val_protector = CAValidationProtector(self.protector)

    def test_encrypt_config(self):
        config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://test",
                        username="user1",
                        password="pass1",
                        headers=[
                            CAHTTPHeader(name="h1", value="v1", secret=True),
                            CAHTTPHeader(name="h2", value="v2", secret=False),
                        ],
                    )
                ]
            )
        )
        encrypted = self.val_protector.encrypt_config(config.model_copy(deep=True))

        check = encrypted.san_validation.http_checks[0]
        self.assertEqual(check.username, "enc_user1")
        self.assertEqual(check.password, "enc_pass1")
        self.assertEqual(check.headers[0].value, "enc_v1")
        self.assertEqual(check.headers[1].value, "v2")

    def test_decrypt_config(self):
        config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://test",
                        username="enc_user1",
                        password="enc_pass1",
                        headers=[
                            CAHTTPHeader(name="h1", value="enc_v1", secret=True),
                            CAHTTPHeader(name="h2", value="v2", secret=False),
                        ],
                    )
                ]
            )
        )
        decrypted = self.val_protector.decrypt_config(config.model_copy(deep=True))

        check = decrypted.san_validation.http_checks[0]
        self.assertEqual(check.username, "user1")
        self.assertEqual(check.password, "pass1")
        self.assertEqual(check.headers[0].value, "v1")
        self.assertEqual(check.headers[1].value, "v2")

    def test_mask_config(self):
        config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://test",
                        username="user1",
                        password="pass1",
                        headers=[
                            CAHTTPHeader(name="h1", value="v1", secret=True),
                            CAHTTPHeader(name="h2", value="v2", secret=False),
                        ],
                    )
                ]
            )
        )
        masked = self.val_protector.mask_config(config.model_copy(deep=True))

        check = masked.san_validation.http_checks[0]
        self.assertEqual(check.username, "*****")
        self.assertEqual(check.password, "*****")
        self.assertEqual(check.headers[0].value, "*****")
        self.assertEqual(check.headers[1].value, "v2")

    def test_backward_compatibility_headers(self):
        # Test that old Dict[str, str] headers are converted to List[CAHTTPHeader]
        data = {"url": "http://test", "headers": {"X-Auth": "secret"}}
        config = CAHTTPValidation(**data)
        self.assertEqual(len(config.headers), 1)
        self.assertEqual(config.headers[0].name, "X-Auth")
        self.assertEqual(config.headers[0].value, "secret")
        self.assertFalse(config.headers[0].secret)

    def test_merge_secrets(self):
        old_config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://test",
                        method="GET",
                        username="old_user",
                        password="old_pass",
                        headers=[
                            CAHTTPHeader(name="h1", value="old_v1", secret=True),
                        ],
                    )
                ]
            )
        )
        new_config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://test",
                        method="GET",
                        username="*****",
                        password="new_pass",
                        headers=[
                            CAHTTPHeader(name="h1", value="*****", secret=True),
                            CAHTTPHeader(name="h2", value="new_v2", secret=True),
                        ],
                    )
                ]
            )
        )

        merged = self.val_protector.merge_secrets(new_config, old_config)

        check = merged.san_validation.http_checks[0]
        self.assertEqual(check.username, "old_user")
        self.assertEqual(check.password, "new_pass")
        self.assertEqual(check.headers[0].value, "old_v1")
        self.assertEqual(check.headers[1].value, "new_v2")
