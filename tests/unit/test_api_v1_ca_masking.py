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

"""Secret-masking tests for the CA authority / space controllers.

``_mask`` is the secret-protection feature that scrubs credentials out of
``validation_config`` before it is returned to a client. It was previously
untested end to end.
"""

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.ca_spaces import ControllerApiV1CASpaces
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
    CAHTTPHeader,
)


def _config_with_secrets():
    return CAValidationConfig(
        san_validation=CASANValidation(
            http_checks=[
                CAHTTPValidation(
                    url="https://validate.example.com",
                    basic_auth_enabled=True,
                    username="admin",
                    password="topsecret",
                    headers=[
                        CAHTTPHeader(name="X-Api-Key", value="leak-me", secret=True),
                        CAHTTPHeader(name="X-Public", value="public", secret=False),
                    ],
                )
            ]
        )
    )


class _MaskMixin:
    controller_cls = None
    controller_kwargs = None

    def _make_controller(self):
        return self.controller_cls(**self.controller_kwargs)

    def test_mask_scrubs_credentials(self):
        controller = self._make_controller()
        data = SimpleNamespace(validation_config=_config_with_secrets())

        result = controller._mask(data)

        check = result.validation_config.san_validation.http_checks[0]
        self.assertEqual(check.username, "*****")
        self.assertEqual(check.password, "*****")
        # secret header value is masked, non-secret header is preserved
        secret_header = next(h for h in check.headers if h.name == "X-Api-Key")
        public_header = next(h for h in check.headers if h.name == "X-Public")
        self.assertEqual(secret_header.value, "*****")
        self.assertEqual(public_header.value, "public")

    def test_mask_noop_without_validation_config(self):
        controller = self._make_controller()
        data = SimpleNamespace(validation_config=None)
        result = controller._mask(data)
        self.assertIsNone(result.validation_config)


class TestCAAuthoritiesMasking(_MaskMixin, unittest.TestCase):
    def setUp(self):
        self.controller_cls = ControllerApiV1CAAuthorities
        self.controller_kwargs = dict(
            log=logging.getLogger("test"),
            authorize=MagicMock(),
            crud_authorities=MagicMock(),
            crud_teams=MagicMock(),
            ca_service=MagicMock(),
        )


class TestCASpacesMasking(_MaskMixin, unittest.TestCase):
    def setUp(self):
        self.controller_cls = ControllerApiV1CASpaces
        self.controller_kwargs = dict(
            log=logging.getLogger("test"),
            authorize=MagicMock(),
            crud_ca_spaces=MagicMock(),
            crud_ca_authorities=MagicMock(),
            crud_ca_certificates=MagicMock(),
            crud_teams=MagicMock(),
            ca_service=MagicMock(),
        )


if __name__ == "__main__":
    unittest.main()
