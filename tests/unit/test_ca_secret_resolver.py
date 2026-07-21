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

from pyppetdb.ca import secret_resolver as sr
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
    CAHTTPHeader,
)


def _check(**kwargs):
    kwargs.setdefault("url", "https://validate.example.com")
    return CAHTTPValidation(**kwargs)


def _config(check):
    return CAValidationConfig(san_validation=CASANValidation(http_checks=[check]))


class TestFindReferences(unittest.TestCase):
    def test_single_reference(self):
        self.assertEqual(sr.find_references("$secrets[TOKEN]"), {"TOKEN"})

    def test_embedded_reference(self):
        self.assertEqual(sr.find_references("Bearer $secrets[TOKEN]"), {"TOKEN"})

    def test_multiple_references(self):
        self.assertEqual(
            sr.find_references("$secrets[A]-$secrets[B]"), {"A", "B"}
        )

    def test_none_and_empty(self):
        self.assertEqual(sr.find_references(None), set())
        self.assertEqual(sr.find_references(""), set())

    def test_escaped_is_not_a_reference(self):
        self.assertEqual(sr.find_references("$$secrets[LITERAL]"), set())

    def test_no_reference(self):
        self.assertEqual(sr.find_references("plain string"), set())


class TestResolveString(unittest.TestCase):
    def test_whole_value(self):
        self.assertEqual(
            sr.resolve_string("$secrets[TOK]", {"TOK": "abc"}), "abc"
        )

    def test_embedded_interpolation(self):
        self.assertEqual(
            sr.resolve_string("Bearer $secrets[TOK]", {"TOK": "abc"}),
            "Bearer abc",
        )

    def test_multiple_interpolation(self):
        self.assertEqual(
            sr.resolve_string("$secrets[A]:$secrets[B]", {"A": "1", "B": "2"}),
            "1:2",
        )

    def test_escape_becomes_literal(self):
        self.assertEqual(
            sr.resolve_string("x $$secrets[LIT] y", {}), "x $secrets[LIT] y"
        )

    def test_missing_reference_fails_closed(self):
        with self.assertRaises(sr.MissingSecretReference) as ctx:
            sr.resolve_string("$secrets[MISSING]", {})
        self.assertEqual(ctx.exception.secret_id, "MISSING")

    def test_none_passthrough(self):
        self.assertIsNone(sr.resolve_string(None, {}))


class TestConfigLevel(unittest.TestCase):
    def test_extract_references_across_all_fields(self):
        check = _check(
            headers=[CAHTTPHeader(name="Authorization", value="Bearer $secrets[H]")],
            password="$secrets[P]",
            body_template='{"k":"$secrets[B]"}',
            client_key="$secrets[K]",
        )
        self.assertEqual(
            sr.extract_references(_config(check)), {"H", "P", "B", "K"}
        )

    def test_extract_ignores_username_and_url(self):
        check = _check(
            url="https://host/$secrets[URLSECRET]",
            username="$secrets[USER]",
        )
        # username is plain text, url refs are surfaced separately
        self.assertEqual(sr.extract_references(_config(check)), set())

    def test_extract_url_references(self):
        check = _check(url="https://host/$secrets[URLSECRET]")
        self.assertEqual(
            sr.extract_url_references(_config(check)), {"URLSECRET"}
        )

    def test_empty_config(self):
        self.assertEqual(sr.extract_references(CAValidationConfig()), set())


class TestResolveCheck(unittest.TestCase):
    def test_resolves_all_fields_and_leaves_original_untouched(self):
        check = _check(
            headers=[CAHTTPHeader(name="Authorization", value="Bearer $secrets[H]")],
            password="$secrets[P]",
            body_template='{"k":"$secrets[B]"}',
            client_key="$secrets[K]",
        )
        resolved = sr.resolve_check(
            check, {"H": "htok", "P": "pw", "B": "btok", "K": "PEM"}
        )
        self.assertEqual(resolved.headers[0].value, "Bearer htok")
        self.assertEqual(resolved.password, "pw")
        self.assertEqual(resolved.body_template, '{"k":"btok"}')
        self.assertEqual(resolved.client_key, "PEM")
        # original object is not mutated
        self.assertEqual(check.password, "$secrets[P]")
        self.assertEqual(check.headers[0].value, "Bearer $secrets[H]")

    def test_resolve_check_fails_closed(self):
        check = _check(password="$secrets[NOPE]")
        with self.assertRaises(sr.MissingSecretReference):
            sr.resolve_check(check, {})


if __name__ == "__main__":
    unittest.main()
