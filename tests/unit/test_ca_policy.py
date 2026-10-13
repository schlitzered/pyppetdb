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

from pyppetdb.ca.policy import allowed_extensions
from pyppetdb.ca.policy import injected_sans
from pyppetdb.ca.policy import signing_policy
from pyppetdb.model.ca_validation import CASANInjection
from pyppetdb.model.ca_validation import CASANValidation
from pyppetdb.model.ca_validation import CAValidationConfig


class TestSigningPolicy(unittest.TestCase):
    def test_allowed_extensions_intersect_when_both_set(self):
        ca = CAValidationConfig(allowed_extensions=["1.1", "1.2", "1.3"])
        space = CAValidationConfig(allowed_extensions=["1.3", "1.2", "9.9"])

        self.assertEqual(allowed_extensions(ca, space), ["1.2", "1.3"])

    def test_allowed_extensions_use_the_one_that_is_set(self):
        ca = CAValidationConfig(allowed_extensions=["1.1"])

        self.assertEqual(allowed_extensions(ca, CAValidationConfig()), ["1.1"])
        self.assertEqual(allowed_extensions(CAValidationConfig(), ca), ["1.1"])

    def test_allowed_extensions_none_when_unset(self):
        self.assertIsNone(
            allowed_extensions(CAValidationConfig(), CAValidationConfig())
        )

    def test_space_key_usages_win_over_ca(self):
        ca = CAValidationConfig(key_usages=["digital_signature"])
        space = CAValidationConfig(key_usages=["key_encipherment"])

        policy = signing_policy(MagicMock(), "node1", ca, space)

        self.assertTrue(policy.key_usages["key_encipherment"])
        self.assertFalse(policy.key_usages["digital_signature"])

    def test_ca_key_usages_apply_when_space_has_none(self):
        ca = CAValidationConfig(key_usages=["crl_sign"])
        space = CAValidationConfig(key_usages=None)

        policy = signing_policy(MagicMock(), "node1", ca, space)

        self.assertTrue(policy.key_usages["crl_sign"])

    def test_requested_sans_honored_only_with_san_validation(self):
        plain = CAValidationConfig()
        validated = CAValidationConfig(san_validation=CASANValidation())

        self.assertFalse(
            signing_policy(MagicMock(), "n", plain, plain).honor_requested_sans
        )
        self.assertTrue(
            signing_policy(MagicMock(), "n", plain, validated).honor_requested_sans
        )

    def test_injected_sans_are_sorted_and_unique(self):
        config = CAValidationConfig(
            san_injection=[
                CASANInjection(pattern="web(\\d)", templates=["b{1}.x", "a{1}.x"]),
                CASANInjection(pattern="web.*", templates=["a1.x"]),
            ]
        )

        self.assertEqual(
            injected_sans(MagicMock(), "web1", [config]), ["a1.x", "b1.x"]
        )

    def test_broken_template_is_logged_and_skipped(self):
        log = MagicMock()
        config = CAValidationConfig(
            san_injection=[CASANInjection(pattern="web1", templates=["{5}.x", "ok.x"])]
        )

        self.assertEqual(injected_sans(log, "web1", [config]), ["ok.x"])
        log.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
