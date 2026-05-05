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
import logging
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.errors import QueryParamValidationError


class TestCrudHieraKeyModelsStaticUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_pyhiera = MagicMock()
        self.crud = CrudHieraKeyModelsStatic(
            self.mock_config, self.log, self.mock_pyhiera
        )

    async def test_get_success(self):
        mock_model_type = MagicMock()
        mock_model_type.return_value.description = "desc"
        self.mock_pyhiera.hiera.key_models = {"static:test": mock_model_type}

        result = await self.crud.get(_id="static:test")
        self.assertEqual(result.id, "static:test")
        self.assertEqual(result.description, "desc")

    async def test_get_not_found(self):
        self.mock_pyhiera.hiera.key_models = {}
        with self.assertRaises(QueryParamValidationError):
            await self.crud.get(_id="static:unknown")

    async def test_get_invalid_prefix(self):
        with self.assertRaises(QueryParamValidationError):
            await self.crud.get(_id="dynamic:test")

    async def test_search(self):
        mock_model1_type = MagicMock()
        mock_model1 = mock_model1_type.return_value
        mock_model1.description = "desc1"

        mock_model2_type = MagicMock()
        mock_model2 = mock_model2_type.return_value
        mock_model2.description = "desc2"

        self.mock_pyhiera.hiera.key_models = {
            "static:test1": mock_model1_type,
            "static:test2": mock_model2_type,
            "dynamic:other": MagicMock(),
        }

        # Test basic search
        result = await self.crud.search(_id="test1")
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].id, "static:test1")

        # Test sort
        result = await self.crud.search(sort="id", sort_order="descending")
        self.assertEqual(result.result[0].id, "static:test2")

        # Test pagination
        result = await self.crud.search(limit=1)
        self.assertEqual(len(result.result), 1)

    def test_build_item_with_model_field(self):
        mock_model_type = MagicMock()
        mock_model = mock_model_type.return_value
        mock_model.description = "desc"
        mock_model.model.model_json_schema.return_value = {"properties": {}}

        item = self.crud._build_item("static:test", mock_model_type, fields=["model"])
        self.assertEqual(item.id, "static:test")
        self.assertEqual(item.model, {"properties": {}})

    async def test_search_invalid_regex(self):
        with self.assertRaises(QueryParamValidationError):
            await self.crud.search(_id="[")
