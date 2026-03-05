import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.hiera_levels import ControllerApiV1HieraLevels
from pyppetdb.model.hiera_levels import HieraLevelPost, HieraLevelPut

class TestApiV1HieraLevelsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_levels = MagicMock()
        self.mock_crud_level_data = MagicMock()
        self.mock_cache = MagicMock()
        
        self.controller = ControllerApiV1HieraLevels(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_levels=self.mock_crud_levels,
            crud_hiera_level_data=self.mock_crud_level_data,
            crud_hiera_lookup_cache=self.mock_cache
        )

    async def test_create_level_clears_cache(self):
        self.mock_authorize.require_admin = AsyncMock()
        
        mock_result = MagicMock()
        mock_result.priority = 10
        self.mock_crud_levels.create = AsyncMock(return_value=mock_result)
        self.mock_crud_level_data.update_priority_by_level = AsyncMock()
        self.mock_cache.clear_all = AsyncMock()
        
        data = HieraLevelPost(priority=10)
        mock_request = MagicMock()
        await self.controller.create(request=mock_request, data=data, level_id="level1", fields=set())
        
        self.mock_authorize.require_admin.assert_called_once()
        self.mock_crud_level_data.update_priority_by_level.assert_called_once_with(level_id="level1", priority=10)
        self.mock_cache.clear_all.assert_called_once()

    async def test_delete_level_clears_cache(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_levels.delete = AsyncMock()
        self.mock_cache.clear_all = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, level_id="level1")
        
        self.mock_cache.clear_all.assert_called_once()
        self.mock_crud_levels.delete.assert_called_once_with(_id="level1")

    async def test_update_level_clears_cache(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_levels.update = AsyncMock()
        self.mock_crud_level_data.update_priority_by_level = AsyncMock()
        self.mock_cache.clear_all = AsyncMock()
        
        data = HieraLevelPut(priority=20)
        mock_request = MagicMock()
        await self.controller.update(request=mock_request, data=data, level_id="level1", fields=set())
        
        self.mock_crud_level_data.update_priority_by_level.assert_called_once_with(level_id="level1", priority=20)
        self.mock_cache.clear_all.assert_called_once()

    async def test_get_level(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_levels.get = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.get(request=mock_request, level_id="level1", fields=set())
        
        self.mock_crud_levels.get.assert_called_once()

    async def test_search_levels(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_levels.search = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            level_id=None,
            priority=None,
            fields=set(),
            sort="priority",
            sort_order="ascending",
            page=0,
            limit=10
        )
        
        self.mock_crud_levels.search.assert_called_once()
