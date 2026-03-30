import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.hiera_keys import ControllerApiV1HieraKeys
from pyppetdb.model.hiera_keys import HieraKeyPost, HieraKeyPut


class TestApiV1HieraKeysUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_static = MagicMock()
        self.mock_crud_dynamic = MagicMock()
        self.mock_crud_keys = MagicMock()
        self.mock_crud_level_data = MagicMock()
        self.mock_pyhiera = MagicMock()

        self.controller = ControllerApiV1HieraKeys(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_key_models_static=self.mock_crud_static,
            crud_hiera_key_models_dynamic=self.mock_crud_dynamic,
            crud_hiera_keys=self.mock_crud_keys,
            crud_hiera_level_data=self.mock_crud_level_data,
            pyhiera=self.mock_pyhiera,
        )

    async def test_key_model_exists_dynamic(self):
        self.mock_crud_dynamic.get = AsyncMock()
        await self.controller._key_model_exists("dynamic:test")
        self.mock_crud_dynamic.get.assert_called_once_with(
            _id="dynamic:test", fields=["id"]
        )

    async def test_key_model_exists_static(self):
        self.mock_crud_static.get = MagicMock()
        await self.controller._key_model_exists("static:test")
        self.mock_crud_static.get.assert_called_once_with(
            _id="static:test", fields=["id"]
        )

    async def test_create_key(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_dynamic.get = AsyncMock()  # For _key_model_exists
        self.mock_crud_keys.create = AsyncMock()

        data = HieraKeyPost(key_model_id="dynamic:test")
        mock_request = MagicMock()
        await self.controller.create(
            request=mock_request, data=data, key_id="key1", fields=set()
        )

        self.mock_authorize.require_admin.assert_called_once()
        self.mock_crud_keys.create.assert_called_once()

    async def test_update_key_with_validation(self):
        self.mock_authorize.require_admin = AsyncMock()
        # Mock current key
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        # Mock _key_model_exists for new model
        self.mock_crud_dynamic.get = AsyncMock()

        # Mock existing data validation cascade
        mock_level_data = MagicMock()
        mock_level_data.result = [MagicMock(data={"foo": "bar"})]
        self.mock_crud_level_data.search = AsyncMock(return_value=mock_level_data)

        # Mock validation success
        self.mock_pyhiera.hiera.key_models = {"dynamic:new": MagicMock()}
        self.mock_crud_keys.update = AsyncMock()

        data = HieraKeyPut(key_model_id="dynamic:new")
        mock_request = MagicMock()
        await self.controller.update(
            request=mock_request, data=data, key_id="key1", fields=set()
        )

        self.mock_crud_level_data.search.assert_called_once()
        self.mock_crud_keys.update.assert_called_once()

    async def test_delete_key(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, key_id="key1")

        self.mock_crud_keys.delete.assert_called_once_with(_id="key1")

    async def test_get_key(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(request=mock_request, key_id="key1", fields=set())

        self.mock_crud_keys.get.assert_called_once()

    async def test_search_keys(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            key_id="key1",
            key_model_id="static:test",
            deprecated=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_crud_keys.search.assert_called_once()
