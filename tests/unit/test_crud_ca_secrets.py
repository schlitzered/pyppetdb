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

from pyppetdb.crud.ca_secrets import CrudCASecrets
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.model.ca_secrets import CASecretGet, CASecretPost, CASecretPut


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class TestCrudCASecretsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.config = MagicMock()
        self.coll = MagicMock()
        # real protector so encryption is actually exercised
        self.protector = NodesDataProtector(
            app_secret_key="unit-test-key", log=self.log
        )
        self.crud = CrudCASecrets(
            config=self.config,
            log=self.log,
            coll=self.coll,
            protector=self.protector,
        )

    async def test_create_encrypts_secret_at_rest(self):
        captured = {}

        async def fake_create(payload, fields):
            captured.update(payload)
            return {"id": payload["id"], "description": payload.get("description")}

        self.crud._create = AsyncMock(side_effect=fake_create)

        await self.crud.create(
            _id="TOKEN",
            payload=CASecretPost(secret="supersecret", description="gh token"),
            fields=["id"],
        )

        # value stored is encrypted, not the cleartext
        self.assertIn("secret_encrypted", captured)
        self.assertNotEqual(captured["secret_encrypted"], "supersecret")
        self.assertEqual(
            self.protector.decrypt_string(captured["secret_encrypted"]),
            "supersecret",
        )
        self.assertIn("created", captured)
        self.assertIn("updated", captured)

    async def test_create_return_never_leaks_secret(self):
        self.crud._create = AsyncMock(
            return_value={
                "id": "TOKEN",
                "description": "d",
                # even if the backend echoed these back, the model must drop them
                "secret_encrypted": "enc",
            }
        )
        result = await self.crud.create(
            _id="TOKEN", payload=CASecretPost(secret="x"), fields=["id"]
        )
        self.assertIsInstance(result, CASecretGet)
        dumped = result.model_dump()
        self.assertNotIn("secret", dumped)
        self.assertNotIn("secret_encrypted", dumped)

    async def test_update_reencrypts_only_when_secret_present(self):
        captured = {}

        async def fake_update(query, payload, fields):
            captured.update(payload)
            return {"id": "TOKEN"}

        self.crud._update = AsyncMock(side_effect=fake_update)

        await self.crud.update(
            _id="TOKEN", payload=CASecretPut(secret="rotated"), fields=["id"]
        )
        self.assertEqual(
            self.protector.decrypt_string(captured["secret_encrypted"]), "rotated"
        )
        self.assertIn("updated", captured)

        captured.clear()
        await self.crud.update(
            _id="TOKEN", payload=CASecretPut(description="only desc"), fields=["id"]
        )
        self.assertNotIn("secret_encrypted", captured)
        self.assertEqual(captured["description"], "only desc")

    async def test_get_values_decrypts(self):
        self.coll.find = MagicMock(
            return_value=_AsyncIter(
                [
                    {"id": "A", "secret_encrypted": self.protector.encrypt_string("sa")},
                    {"id": "B", "secret_encrypted": self.protector.encrypt_string("sb")},
                ]
            )
        )
        result = await self.crud.get_values(["A", "B"])
        self.assertEqual(result, {"A": "sa", "B": "sb"})

    async def test_get_values_empty_input(self):
        self.coll.find = MagicMock()
        result = await self.crud.get_values([])
        self.assertEqual(result, {})
        self.coll.find.assert_not_called()

    async def test_existing_ids(self):
        self.coll.find = MagicMock(
            return_value=_AsyncIter([{"id": "A"}, {"id": "C"}])
        )
        result = await self.crud.existing_ids(["A", "B", "C"])
        self.assertEqual(result, {"A", "C"})


if __name__ == "__main__":
    unittest.main()
