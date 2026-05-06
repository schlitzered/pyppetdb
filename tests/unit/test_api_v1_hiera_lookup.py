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
from pyppetdb.authorize import PERM_HIERA_GET
from pyppetdb.controller.api.v1.hiera_lookup import ControllerApiV1HieraLookup
from pyppetdb.errors import QueryParamValidationError


class TestApiV1HieraLookupUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_keys = MagicMock()
        self.mock_pyhiera = MagicMock()
        self.mock_pyhiera.hiera = MagicMock()

        self.controller = ControllerApiV1HieraLookup(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_lookup_cache=self.mock_cache,
            crud_hiera_keys=self.mock_keys,
            pyhiera=self.mock_pyhiera,
        )

    def test_facts_from_query(self):
        # Valid facts
        facts = {"os:linux", "role:web"}
        result = self.controller._facts_from_query(facts)
        self.assertEqual(result, {"os": "linux", "role": "web"})

        # Invalid facts (missing colon)
        with self.assertRaises(QueryParamValidationError):
            self.controller._facts_from_query({"invalid"})

        # Invalid facts (empty value)
        with self.assertRaises(QueryParamValidationError):
            self.controller._facts_from_query({"os:"})

    async def test_lookup_cached(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_cache.get_cached = AsyncMock(
            return_value={"result": {"data": "cached-value"}}
        )

        mock_request = MagicMock()
        result = await self.controller.lookup(
            request=mock_request, key_id="mykey", fact={"os:linux"}
        )

        self.assertEqual(result.data, "cached-value")
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_GET
        )
        self.mock_pyhiera.hiera.key_data_get.assert_not_called()

    async def test_lookup_no_cache(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_cache.get_cached = AsyncMock(return_value=None)
        self.mock_cache.set_cached = AsyncMock()

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"data": "fresh-value", "sources": []}
        self.mock_pyhiera.hiera.key_data_get = AsyncMock(return_value=mock_data)

        mock_request = MagicMock()
        result = await self.controller.lookup(
            request=mock_request, key_id="mykey", fact=set(), merge=False
        )

        self.assertEqual(result.data, "fresh-value")
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_GET
        )
        self.mock_pyhiera.hiera.key_data_get.assert_called_once()
        self.mock_cache.set_cached.assert_called_once()
