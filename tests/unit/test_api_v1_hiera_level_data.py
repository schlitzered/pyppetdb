import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.hiera_level_data import ControllerApiV1HieraLevelData
from pyppetdb.model.hiera_level_data import HieraLevelDataPost, HieraLevelDataPut
from pyppetdb.errors import QueryParamValidationError


class TestApiV1HieraLevelDataUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_static = MagicMock()
        self.mock_crud_dynamic = MagicMock()
        self.mock_crud_keys = MagicMock()
        self.mock_crud_level_data = MagicMock()
        self.mock_crud_levels = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_pyhiera = MagicMock()
        self.mock_pyhiera.hiera = MagicMock()

        self.controller = ControllerApiV1HieraLevelData(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_key_models_static=self.mock_crud_static,
            crud_hiera_key_models_dynamic=self.mock_crud_dynamic,
            crud_hiera_keys=self.mock_crud_keys,
            crud_hiera_level_data=self.mock_crud_level_data,
            crud_hiera_levels=self.mock_crud_levels,
            crud_hiera_lookup_cache=self.mock_cache,
            pyhiera=self.mock_pyhiera,
        )

    async def test_create_level_data_validation(self):
        self.mock_authorize.require_admin = AsyncMock()
        # Mock key and level existence
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="static:test")
        )
        self.mock_crud_levels.get = AsyncMock(return_value=MagicMock(priority=10))
        self.mock_crud_static.get = MagicMock()

        # Mock model type and validation
        mock_model_type = MagicMock()
        self.mock_pyhiera.hiera.key_models = {"static:test": mock_model_type}

        self.mock_crud_level_data.create = AsyncMock(
            return_value=MagicMock(facts={"os": "linux"})
        )
        self.mock_cache.delete_by_key_and_facts = AsyncMock()

        data = HieraLevelDataPost(data={"foo": "bar"}, facts={"os": "linux"})
        mock_request = MagicMock()
        await self.controller.create(
            request=mock_request,
            data=data,
            level_id="l1",
            data_id="d1",
            key_id="k1",
            fields=set(),
        )

        mock_model_type.return_value.validate.assert_called_once_with({"foo": "bar"})
        self.mock_crud_level_data.create.assert_called_once()
        self.mock_cache.delete_by_key_and_facts.assert_called_once_with(
            key_id="k1", facts={"os": "linux"}
        )

    async def test_create_invalid_data(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="static:test")
        )
        self.mock_crud_levels.get = AsyncMock(return_value=MagicMock(priority=10))

        mock_model_type = MagicMock()
        mock_model_type.return_value.validate.side_effect = ValueError("bad data")
        self.mock_pyhiera.hiera.key_models = {"static:test": mock_model_type}

        data = HieraLevelDataPost(data={"foo": "bar"}, facts={"os": "linux"})
        mock_request = MagicMock()
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller.create(
                request=mock_request,
                data=data,
                level_id="l1",
                data_id="d1",
                key_id="k1",
                fields=set(),
            )
        self.assertIn("invalid data for key model", str(cm.exception))

    async def test_create_missing_key_model(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="static:unknown")
        )
        self.mock_crud_levels.get = AsyncMock(return_value=MagicMock(priority=10))
        self.mock_pyhiera.hiera.key_models = {}

        data = HieraLevelDataPost(data={"foo": "bar"}, facts={"os": "linux"})
        mock_request = MagicMock()
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller.create(
                request=mock_request,
                data=data,
                level_id="l1",
                data_id="d1",
                key_id="k1",
                fields=set(),
            )
        self.assertIn("key model static:unknown not found", str(cm.exception))

    async def test_delete_level_data_clears_cache(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_level_data.get = AsyncMock(
            return_value=MagicMock(facts={"env": "prod"})
        )
        self.mock_crud_level_data.delete = AsyncMock()
        self.mock_cache.delete_by_key_and_facts = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(
            request=mock_request, level_id="l1", data_id="d1", key_id="k1"
        )

        self.mock_crud_level_data.delete.assert_called_once()
        self.mock_cache.delete_by_key_and_facts.assert_called_once_with(
            key_id="k1", facts={"env": "prod"}
        )

    async def test_get(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_level_data.get = AsyncMock(return_value=MagicMock())

        mock_request = MagicMock()
        await self.controller.get(
            request=mock_request, level_id="l1", data_id="d1", key_id="k1", fields=set()
        )

        self.mock_crud_level_data.get.assert_called_once()

    async def test_search(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_level_data.search = AsyncMock(return_value=MagicMock())

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            level_id="l1",
            key_id=None,
            data_id=None,
            fact=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_crud_level_data.search.assert_called_once()

    async def test_update(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="static:test")
        )
        self.mock_crud_levels.get = AsyncMock()

        mock_model_type = MagicMock()
        self.mock_pyhiera.hiera.key_models = {"static:test": mock_model_type}

        self.mock_crud_level_data.get = AsyncMock(
            return_value=MagicMock(facts={"os": "linux"})
        )
        self.mock_crud_level_data.update = AsyncMock(return_value=MagicMock())
        self.mock_cache.delete_by_key_and_facts = AsyncMock()

        data = HieraLevelDataPut(data={"foo": "new-bar"})
        mock_request = MagicMock()
        await self.controller.update(
            request=mock_request,
            data=data,
            level_id="l1",
            data_id="d1",
            key_id="k1",
            fields=set(),
        )

        mock_model_type.return_value.validate.assert_called_once_with(
            {"foo": "new-bar"}
        )
        self.mock_crud_level_data.update.assert_called_once()
        self.mock_cache.delete_by_key_and_facts.assert_called_once_with(
            key_id="k1", facts={"os": "linux"}
        )
