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
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_spaces import CrudCASpaces


class TestCrudCASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_protector = MagicMock()
        self.mock_crud_secrets = AsyncMock()
        self.mock_crud_secrets.existing_ids = AsyncMock(return_value=set())

        self.crud = CrudCASpaces(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector,
            crud_secrets=self.mock_crud_secrets,
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="space1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "space1"})

    async def test_create(self):
        from pyppetdb.model.ca_spaces import CASpacePost

        self.crud._create = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca1", "ca_id_history": []}
        )
        payload_dict = {"ca_id": "ca1"}
        payload = CASpacePost(**payload_dict)
        await self.crud.create(_id="space1", payload=payload, fields=["id"])

        self.crud._create.assert_called_once()

    async def test_update(self):
        from pyppetdb.model.ca_spaces import CASpacePutInternal

        self.crud._update = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca2", "ca_id_history": ["ca1"]}
        )

        payload_dict = {"ca_id": "ca2", "ca_id_history": ["ca1"]}
        payload = CASpacePutInternal(**payload_dict)
        await self.crud.update(_id="space1", payload=payload, fields=["id"])

        self.crud._update.assert_called_once()

    async def test_search_by_ca(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "s1"}])
        self.mock_coll.find.return_value = mock_cursor

        res = await self.crud.search_by_ca("ca1")
        self.assertEqual(len(res), 1)
        self.mock_coll.find.assert_called_once()
        args = self.mock_coll.find.call_args[0][0]
        self.assertIn("$or", args)
