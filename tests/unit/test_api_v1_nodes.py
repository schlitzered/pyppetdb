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
from pyppetdb.authorize import (
    PERM_NODES_CREATE,
    PERM_NODES_UPDATE,
    PERM_NODES_DELETE,
    PERM_NODES_CATALOG_CACHE_DELETE,
)
from pyppetdb.controller.api.v1.nodes import ControllerApiV1Nodes
from pyppetdb.model.nodes import NodePut


class TestApiV1NodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_nodes.get_placement = AsyncMock(return_value={})
        self.mock_crud_catalog_cache = MagicMock()
        self.mock_crud_catalogs = MagicMock()
        self.mock_crud_groups = MagicMock()
        self.mock_crud_reports = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_crud_jobs = MagicMock()
        self.mock_crud_jobs.remove_node_from_jobs = AsyncMock()
        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_node_jobs.delete_by_node = AsyncMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1Nodes(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_catalog_cache=self.mock_crud_catalog_cache,
            crud_nodes_catalogs=self.mock_crud_catalogs,
            crud_nodes_groups=self.mock_crud_groups,
            crud_nodes_reports=self.mock_crud_reports,
            crud_teams=self.mock_crud_teams,
            crud_jobs=self.mock_crud_jobs,
            crud_node_jobs=self.mock_crud_node_jobs,
            ca_service=self.mock_ca_service,
        )

    async def test_get_node(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(
            node_id="node1", request=mock_request, fields=set(), outdated_threshold=None
        )

        self.mock_authorize.require_user.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.get.assert_called_once_with(
            _id="node1", user_node_groups=[], fields=[], outdated_threshold=None
        )

    async def test_delete_node_cascades(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.update_certificate_status = AsyncMock()
        self.mock_crud_groups.delete_node_from_nodes_groups = AsyncMock()
        self.mock_crud_catalogs.delete_all_from_node = AsyncMock()
        self.mock_crud_reports.delete_all_from_node = AsyncMock()
        self.mock_crud_jobs.remove_node_from_jobs = AsyncMock()
        self.mock_crud_node_jobs.delete_by_node = AsyncMock()
        self.mock_crud_nodes.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_id="node1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_DELETE
        )
        self.mock_ca_service.update_certificate_status.assert_called_once()
        self.mock_crud_groups.delete_node_from_nodes_groups.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_catalogs.delete_all_from_node.assert_called_once_with(
            node_id="node1",
            placement={},
        )
        self.mock_crud_reports.delete_all_from_node.assert_called_once_with(
            node_id="node1",
            placement={},
        )
        self.mock_crud_jobs.remove_node_from_jobs.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_node_jobs.delete_by_node.assert_called_once_with(node_id="node1")
        self.mock_crud_nodes.delete.assert_called_once_with(_id="node1")

    async def test_update_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes.update = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.update(
            node_id="node1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_UPDATE
        )
        self.mock_crud_nodes.update.assert_called_once()
        args = self.mock_crud_nodes.update.call_args[1]
        self.assertEqual(args["_id"], "node1")
        self.assertEqual(args["payload"].disabled, True)

    async def test_create_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes.create = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.create(
            node_id="node2", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_CREATE
        )
        self.mock_crud_nodes.create.assert_called_once()
        args = self.mock_crud_nodes.create.call_args[1]
        self.assertEqual(args["_id"], "node2")
        self.assertEqual(args["payload"].disabled, True)

    async def test_catalog_cache_wipe_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_catalog_cache.delete_many_by_filter = AsyncMock()

        mock_request = MagicMock()
        await self.controller.catalog_cache_wipe(
            request=mock_request, node_id="node1", environment="prod", fact=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_CATALOG_CACHE_DELETE
        )
        self.mock_crud_catalog_cache.delete_many_by_filter.assert_called_once_with(
            node_id="node1", environment="prod", fact=set()
        )


class TestApiV1NodesEnrichmentUnit(unittest.IsolatedAsyncioTestCase):
    """Coverage for the exported_resources handler and the catalog_cached
    enrichment branches in get()/search(), none of which were previously
    exercised."""

    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize.require_user = AsyncMock(return_value=MagicMock(id="admin"))
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=["group-a"])
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_catalog_cache = MagicMock()

        self.controller = ControllerApiV1Nodes(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_catalog_cache=self.mock_crud_catalog_cache,
            crud_nodes_catalogs=MagicMock(),
            crud_nodes_groups=MagicMock(),
            crud_nodes_reports=MagicMock(),
            crud_teams=MagicMock(),
            crud_jobs=MagicMock(),
            crud_node_jobs=MagicMock(),
            ca_service=MagicMock(),
        )

    async def test_exported_resources(self):
        self.mock_crud_nodes.exported_resources = AsyncMock(return_value={"ok": True})
        request = MagicMock()

        result = await self.controller.exported_resources(
            request=request,
            resource_type="Nginx::Vhost",
            resource_title=None,
            resource_tags=None,
            disabled=None,
            environment=None,
            fact=None,
        )

        self.mock_authorize.require_user.assert_called_once_with(request=request)
        self.mock_crud_nodes.exported_resources.assert_called_once()
        _, kwargs = self.mock_crud_nodes.exported_resources.call_args
        self.assertEqual(kwargs["resource_type"], "Nginx::Vhost")
        self.assertEqual(kwargs["user_node_groups"], ["group-a"])
        self.assertEqual(result, {"ok": True})

    async def test_get_sets_catalog_cached_true(self):
        node = MagicMock()
        self.mock_crud_nodes.get = AsyncMock(return_value=node)
        self.mock_crud_catalog_cache.get_cached_node_ids = AsyncMock(
            return_value=["node1"]
        )

        result = await self.controller.get(
            node_id="node1", request=MagicMock(), fields={"id", "catalog_cached"}
        )
        self.assertTrue(result.catalog_cached)

    async def test_get_sets_catalog_cached_false(self):
        node = MagicMock()
        self.mock_crud_nodes.get = AsyncMock(return_value=node)
        self.mock_crud_catalog_cache.get_cached_node_ids = AsyncMock(return_value=[])

        result = await self.controller.get(
            node_id="node1", request=MagicMock(), fields={"id", "catalog_cached"}
        )
        self.assertFalse(result.catalog_cached)

    async def test_get_without_catalog_cached_field_skips_cache(self):
        node = MagicMock()
        self.mock_crud_nodes.get = AsyncMock(return_value=node)
        self.mock_crud_catalog_cache.get_cached_node_ids = AsyncMock()

        await self.controller.get(
            node_id="node1", request=MagicMock(), fields={"id"}
        )
        self.mock_crud_catalog_cache.get_cached_node_ids.assert_not_called()

    async def test_search_enriches_catalog_cached(self):
        n1 = MagicMock(id="node1")
        n2 = MagicMock(id="node2")
        result_obj = MagicMock()
        result_obj.result = [n1, n2]
        self.mock_crud_nodes.search = AsyncMock(return_value=result_obj)
        self.mock_crud_catalog_cache.get_cached_node_ids = AsyncMock(
            return_value=["node1"]
        )

        await self.controller.search(
            request=MagicMock(), fields={"id", "catalog_cached"}
        )

        self.assertTrue(n1.catalog_cached)
        self.assertFalse(n2.catalog_cached)

    async def test_search_catalog_cached_requires_id_field(self):
        result_obj = MagicMock()
        result_obj.result = [MagicMock(id="node1")]
        self.mock_crud_nodes.search = AsyncMock(return_value=result_obj)
        self.mock_crud_catalog_cache.get_cached_node_ids = AsyncMock()

        # guard: catalog_cached without id must NOT trigger the cache lookup
        await self.controller.search(
            request=MagicMock(), fields={"catalog_cached"}
        )
        self.mock_crud_catalog_cache.get_cached_node_ids.assert_not_called()
