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

from pyppetdb.authorize import PERM_TEAMS_GET
from pyppetdb.controller.api.v1.permissions import (
    ControllerApiV1Permissions,
    STATIC_PERMISSIONS,
)


def _search_result(ids):
    result = MagicMock()
    result.result = [MagicMock(id=_id) for _id in ids]
    return result


class TestApiV1PermissionsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_authorities = MagicMock()
        self.mock_ca_spaces = MagicMock()
        self.mock_hiera_keys = MagicMock()
        self.mock_jobs_definitions = MagicMock()

        self.controller = ControllerApiV1Permissions(
            log=self.log,
            authorize=self.mock_authorize,
            crud_ca_authorities=self.mock_ca_authorities,
            crud_ca_spaces=self.mock_ca_spaces,
            crud_hiera_keys=self.mock_hiera_keys,
            crud_jobs_definitions=self.mock_jobs_definitions,
        )

    def _wire_search(self, authorities=(), spaces=(), keys=(), definitions=()):
        self.mock_ca_authorities.search = AsyncMock(
            return_value=_search_result(authorities)
        )
        self.mock_ca_spaces.search = AsyncMock(return_value=_search_result(spaces))
        self.mock_hiera_keys.search = AsyncMock(return_value=_search_result(keys))
        self.mock_jobs_definitions.search = AsyncMock(
            return_value=_search_result(definitions)
        )

    async def test_get_requires_teams_get_permission(self):
        self._wire_search()
        mock_request = MagicMock()

        await self.controller.get(request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_GET
        )

    async def test_get_returns_static_permissions(self):
        self._wire_search()
        result = await self.controller.get(request=MagicMock())
        self.assertEqual(result.static, STATIC_PERMISSIONS)

    async def test_get_empty_dynamic(self):
        self._wire_search()
        result = await self.controller.get(request=MagicMock())
        self.assertEqual(result.dynamic, [])

    async def test_get_builds_dynamic_permissions(self):
        self._wire_search(
            authorities=["ca-a"],
            spaces=["space-a"],
            keys=["key1"],
            definitions=["deploy"],
        )
        result = await self.controller.get(request=MagicMock())

        expected = {
            "CA:AUTHORITIES:ca-a:CERTS:UPDATE",
            "CA:SPACES:space-a:CERTS:UPDATE",
            "HIERA:LEVEL_DATA:key1:CREATE",
            "HIERA:LEVEL_DATA:key1:UPDATE",
            "HIERA:LEVEL_DATA:key1:DELETE",
            "JOBS:JOB:deploy:CREATE",
        }
        self.assertEqual(set(result.dynamic), expected)
        # per hiera key, exactly three dynamic permissions are produced
        self.assertEqual(len(result.dynamic), 6)

    async def test_get_dynamic_is_sorted(self):
        self._wire_search(keys=["zeta", "alpha"])
        result = await self.controller.get(request=MagicMock())
        self.assertEqual(result.dynamic, sorted(result.dynamic))

    async def test_get_searches_use_limit_1000(self):
        self._wire_search()
        await self.controller.get(request=MagicMock())
        for mock in (
            self.mock_ca_authorities.search,
            self.mock_ca_spaces.search,
            self.mock_hiera_keys.search,
            self.mock_jobs_definitions.search,
        ):
            _, kwargs = mock.call_args
            self.assertEqual(kwargs["limit"], 1000)
            self.assertEqual(kwargs["fields"], ["id"])


if __name__ == "__main__":
    unittest.main()
