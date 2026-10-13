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
from datetime import datetime
from datetime import timezone

from pyppetdb.model.ca_authorities import CAAuthorityPostInternal
from pyppetdb.model.ca_authorities import CAAuthorityPutInternal
from pyppetdb.model.ca_spaces import CASpacePostInternal
from pyppetdb.model.ca_spaces import CASpacePutInternal


def _config(*values):
    return {
        "san_validation": {
            "http_checks": [
                {
                    "url": "https://check.example.com",
                    "headers": [
                        {"name": f"h{i}", "value": value}
                        for i, value in enumerate(values)
                    ],
                }
            ]
        }
    }


def _authority(**kwargs):
    now = datetime.now(timezone.utc)
    return CAAuthorityPostInternal(
        id="ca1",
        cn="CA1",
        issuer="CA1",
        serial_number="1",
        not_before=now,
        not_after=now,
        fingerprint={"sha256": "a", "sha1": "b", "md5": "c"},
        certificate="CERT",
        private_key_encrypted="ENC",
        internal=True,
        status="active",
        **kwargs,
    )


class TestCASecretRefs(unittest.TestCase):
    def test_post_derives_sorted_unique_refs(self):
        space = CASpacePostInternal(
            ca_id="ca1",
            validation_config=_config("$secrets[B] $secrets[A]", "$secrets[B]"),
        )

        self.assertEqual(space.secret_refs, ["A", "B"])
        self.assertEqual(space.model_dump()["secret_refs"], ["A", "B"])

    def test_escaped_reference_is_not_a_ref(self):
        space = CASpacePostInternal(
            ca_id="ca1", validation_config=_config("$$secrets[LITERAL]")
        )

        self.assertEqual(space.secret_refs, [])

    def test_post_without_config_stores_empty_refs(self):
        self.assertEqual(CASpacePostInternal(ca_id="ca1").model_dump()["secret_refs"], [])
        self.assertEqual(_authority().model_dump()["secret_refs"], [])

    def test_authority_post_derives_refs(self):
        authority = _authority(validation_config=_config("$secrets[X]"))

        self.assertEqual(authority.secret_refs, ["X"])

    def test_explicit_refs_are_overridden_by_config(self):
        space = CASpacePostInternal(
            ca_id="ca1",
            secret_refs=["FORGED"],
            validation_config=_config("$secrets[REAL]"),
        )

        self.assertEqual(space.secret_refs, ["REAL"])

    def test_put_without_config_leaves_refs_untouched(self):
        for model in (
            CASpacePutInternal(description="new"),
            CAAuthorityPutInternal(status="revoked"),
        ):
            data = model.model_dump(exclude_unset=True)
            self.assertNotIn("secret_refs", data)
            self.assertNotIn("validation_config", data)

    def test_put_with_config_sets_refs(self):
        for model in (
            CASpacePutInternal(validation_config=_config("$secrets[S]")),
            CAAuthorityPutInternal(validation_config=_config("$secrets[S]")),
        ):
            self.assertEqual(model.model_dump(exclude_unset=True)["secret_refs"], ["S"])

    def test_put_with_empty_config_clears_refs(self):
        data = CASpacePutInternal(validation_config={}).model_dump(exclude_unset=True)

        self.assertEqual(data["secret_refs"], [])


if __name__ == "__main__":
    unittest.main()
