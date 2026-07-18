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

"""Cross-cutting authorization tests.

Every other controller unit test replaces ``require_perm`` with a no-op
``AsyncMock`` and therefore only ever exercises the "permission granted"
direction. These tests do the opposite: they make ``require_perm`` raise a
403 ``PermissionError`` and assert that

  1. the handler propagates the 403, and
  2. the underlying CRUD mutation is NOT executed (i.e. the permission check
     actually gates the side effect and nothing runs before it).
"""

import logging
import unittest
from unittest.mock import MagicMock, AsyncMock

from fastapi import HTTPException

from pyppetdb.errors import PermissionError as PyppetPermissionError
from pyppetdb.controller.api.v1.nodes_groups import ControllerApiV1NodesGroups
from pyppetdb.controller.api.v1.teams import ControllerApiV1Teams
from pyppetdb.controller.api.v1.users import ControllerApiV1Users
from pyppetdb.controller.api.v1.hiera_keys import ControllerApiV1HieraKeys
from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.jobs_jobs import ControllerApiV1JobsJobs


def _denying_authorize():
    authorize = MagicMock()
    authorize.require_perm = AsyncMock(side_effect=PyppetPermissionError())
    authorize.require_user = AsyncMock(side_effect=PyppetPermissionError())
    return authorize


class TestAuthorizationDenied(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.authorize = _denying_authorize()
        self.request = MagicMock()

    async def _assert_denied(self, coro):
        with self.assertRaises(HTTPException) as ctx:
            await coro
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_nodes_groups_delete_denied(self):
        crud_nodes = MagicMock()
        crud_nodes.delete_node_group_from_all = AsyncMock()
        crud_groups = MagicMock()
        crud_groups.delete = AsyncMock()
        controller = ControllerApiV1NodesGroups(
            log=self.log,
            authorize=self.authorize,
            crud_nodes=crud_nodes,
            crud_nodes_groups=crud_groups,
            crud_teams=MagicMock(),
        )

        await self._assert_denied(
            controller.delete(request=self.request, node_group_id="g1")
        )
        crud_nodes.delete_node_group_from_all.assert_not_called()
        crud_groups.delete.assert_not_called()

    async def test_teams_delete_denied(self):
        crud_teams = MagicMock()
        crud_teams.delete = AsyncMock()
        crud_groups = MagicMock()
        crud_groups.delete_team_from_nodes_groups = AsyncMock()
        controller = ControllerApiV1Teams(
            log=self.log,
            authorize=self.authorize,
            crud_nodes_groups=crud_groups,
            crud_teams=crud_teams,
            crud_ldap=MagicMock(),
            crud_ca_spaces=MagicMock(),
            crud_ca_authorities=MagicMock(),
            crud_jobs_definitions=MagicMock(),
            crud_hiera_keys=MagicMock(),
        )

        await self._assert_denied(
            controller.delete(request=self.request, team_id="t1")
        )
        crud_teams.delete.assert_not_called()
        crud_groups.delete_team_from_nodes_groups.assert_not_called()

    async def test_users_delete_denied(self):
        crud_users = MagicMock()
        crud_users.delete = AsyncMock()
        controller = ControllerApiV1Users(
            log=self.log,
            authorize=self.authorize,
            crud_teams=MagicMock(),
            crud_users=crud_users,
            crud_users_credentials=MagicMock(),
        )

        await self._assert_denied(
            controller.delete(request=self.request, user_id="u1")
        )
        crud_users.delete.assert_not_called()

    async def test_hiera_keys_delete_denied(self):
        crud_keys = MagicMock()
        crud_keys.delete = AsyncMock()
        controller = ControllerApiV1HieraKeys(
            log=self.log,
            authorize=self.authorize,
            crud_hiera_key_models_static=MagicMock(),
            crud_hiera_key_models_dynamic=MagicMock(),
            crud_hiera_keys=crud_keys,
            crud_hiera_level_data=MagicMock(),
            crud_teams=MagicMock(),
            pyhiera=MagicMock(),
        )

        await self._assert_denied(
            controller.delete(request=self.request, key_id="k1")
        )
        crud_keys.delete.assert_not_called()

    async def test_ca_authorities_delete_denied(self):
        ca_service = MagicMock()
        ca_service.delete_authority = AsyncMock()
        controller = ControllerApiV1CAAuthorities(
            log=self.log,
            authorize=self.authorize,
            crud_authorities=MagicMock(),
            crud_teams=MagicMock(),
            ca_service=ca_service,
        )

        await self._assert_denied(
            controller.delete(request=self.request, ca_id="ca1")
        )
        ca_service.delete_authority.assert_not_called()

    async def test_jobs_jobs_cancel_denied(self):
        # cancel() must first load the job to build the *dynamic* permission
        # (JOBS:JOB:{definition_id}:CREATE), so crud_jobs.get is expected to run
        # before require_perm; the actual mutation must still be gated.
        job = MagicMock()
        job.definition_id = "deploy"
        crud_jobs = MagicMock()
        crud_jobs.get = AsyncMock(return_value=job)
        crud_node_jobs = MagicMock()
        crud_node_jobs.cancel_node_jobs = AsyncMock()
        controller = ControllerApiV1JobsJobs(
            log=self.log,
            config=MagicMock(),
            authorize=self.authorize,
            crud_jobs=crud_jobs,
            crud_jobs_definitions=MagicMock(),
            crud_nodes=MagicMock(),
            crud_jobs_node_jobs=crud_node_jobs,
        )

        await self._assert_denied(
            controller.cancel(request=self.request, job_id="j1")
        )
        crud_node_jobs.cancel_node_jobs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
