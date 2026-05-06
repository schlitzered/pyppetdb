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
from pyppetdb.controller.api.v1.pyppetdb_nodes import ControllerApiV1PyppetDBNodes
from pyppetdb.authorize import PERM_PYPPETDB_NODES_GET
from pyppetdb.authorize import PERM_PYPPETDB_NODES_DELETE


class TestApiV1PyppetDBNodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_pyppetdb_nodes = MagicMock()

        self.controller = ControllerApiV1PyppetDBNodes(
            log=self.log,
            authorize=self.mock_authorize,
            crud_pyppetdb_nodes=self.mock_crud_pyppetdb_nodes,
        )

    async def test_search_nodes_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_pyppetdb_nodes.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            _id=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_PYPPETDB_NODES_GET
        )
        self.mock_crud_pyppetdb_nodes.search.assert_called_once()

    async def test_get_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_pyppetdb_nodes.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(node_id="node1", request=mock_request, fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_PYPPETDB_NODES_GET
        )
        self.mock_crud_pyppetdb_nodes.get.assert_called_once_with(
            _id="node1", fields=[]
        )

    async def test_delete_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_pyppetdb_nodes.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_id="node1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_PYPPETDB_NODES_DELETE
        )
        self.mock_crud_pyppetdb_nodes.delete.assert_called_once_with(_id="node1")
