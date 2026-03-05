import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.hiera_key_models_dynamic import ControllerApiV1HieraKeyModelsDynamic
from pyppetdb.controller.api.v1.hiera_key_models_static import ControllerApiV1HieraKeyModelsStatic
from pyppetdb.model.hiera_key_models_dynamic import HieraKeyModelDynamicPost
from pyppetdb.errors import QueryParamValidationError

class TestApiV1HieraKeyModelsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_dynamic = MagicMock()
        self.mock_crud_static = MagicMock()
        self.mock_crud_keys = MagicMock()
        
        self.dynamic_controller = ControllerApiV1HieraKeyModelsDynamic(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_key_models_dynamic=self.mock_crud_dynamic,
            crud_hiera_keys=self.mock_crud_keys
        )
        
        self.static_controller = ControllerApiV1HieraKeyModelsStatic(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_key_models_static=self.mock_crud_static
        )

    async def test_dynamic_create_success(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_dynamic.create = AsyncMock()
        
        data = HieraKeyModelDynamicPost(model={"type": "object"})
        mock_request = MagicMock()
        await self.dynamic_controller.create(
            request=mock_request, data=data, key_model_id="dynamic:test", fields=set()
        )
        
        self.mock_crud_dynamic.create.assert_called_once()

    async def test_dynamic_create_invalid_prefix(self):
        self.mock_authorize.require_admin = AsyncMock()
        data = HieraKeyModelDynamicPost(model={"type": "object"})
        mock_request = MagicMock()
        
        with self.assertRaises(QueryParamValidationError):
            await self.dynamic_controller.create(
                request=mock_request, data=data, key_model_id="invalid:test", fields=set()
            )

    async def test_dynamic_delete_in_use(self):
        self.mock_authorize.require_admin = AsyncMock()
        
        # Mock keys still using this model
        mock_keys = MagicMock()
        mock_keys.result = [MagicMock(id="key1")]
        self.mock_crud_keys.search = AsyncMock(return_value=mock_keys)
        
        mock_request = MagicMock()
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.dynamic_controller.delete(request=mock_request, key_model_id="dynamic:test")
        
        self.assertIn("still in use", str(cm.exception.detail))
        self.mock_crud_dynamic.delete.assert_not_called()

    async def test_dynamic_get(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_dynamic.get = AsyncMock()
        
        mock_request = MagicMock()
        await self.dynamic_controller.get(request=mock_request, key_model_id="dynamic:test", fields=set())
        self.mock_crud_dynamic.get.assert_called_once()

    async def test_dynamic_search(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_dynamic.search = AsyncMock()
        
        mock_request = MagicMock()
        await self.dynamic_controller.search(
            request=mock_request,
            key_model_id=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10
        )
        self.mock_crud_dynamic.search.assert_called_once()

    async def test_static_get(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_static.get = MagicMock()
        
        mock_request = MagicMock()
        await self.static_controller.get(request=mock_request, key_model_id="static:test", fields=set())
        
        self.mock_authorize.require_admin.assert_called_once()
        self.mock_crud_static.get.assert_called_once()

    async def test_static_search(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_static.search = MagicMock()
        
        mock_request = MagicMock()
        await self.static_controller.search(
            request=mock_request,
            key_model_id=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10
        )
        self.mock_crud_static.search.assert_called_once()
