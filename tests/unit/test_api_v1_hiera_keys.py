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
import re
from pyppetdb.controller.api.v1.hiera_keys import ControllerApiV1HieraKeys
from pyppetdb.model.hiera_keys import HieraKeyPost, HieraKeyPut
from pyppetdb.authorize import PERM_HIERA_GET
from pyppetdb.authorize import PERM_HIERA_KEYS_CREATE
from pyppetdb.authorize import PERM_HIERA_KEYS_DELETE


class TestApiV1HieraKeysUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_static = MagicMock()
        self.mock_crud_dynamic = MagicMock()
        self.mock_crud_keys = MagicMock()
        self.mock_crud_level_data = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_pyhiera = MagicMock()

        self.controller = ControllerApiV1HieraKeys(
            log=self.log,
            authorize=self.mock_authorize,
            crud_hiera_key_models_static=self.mock_crud_static,
            crud_hiera_key_models_dynamic=self.mock_crud_dynamic,
            crud_hiera_keys=self.mock_crud_keys,
            crud_hiera_level_data=self.mock_crud_level_data,
            crud_teams=self.mock_crud_teams,
            pyhiera=self.mock_pyhiera,
        )

    async def test_key_model_exists_dynamic(self):
        self.mock_crud_dynamic.get = AsyncMock()
        await self.controller._key_model_exists("dynamic:test")
        self.mock_crud_dynamic.get.assert_called_once_with(
            _id="dynamic:test", fields=["id"]
        )

    async def test_key_model_exists_static(self):
        self.mock_crud_static.get = AsyncMock()
        await self.controller._key_model_exists("static:test")
        self.mock_crud_static.get.assert_called_once_with(
            _id="static:test", fields=["id"]
        )

    async def test_create_key(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_dynamic.get = AsyncMock()  # For _key_model_exists
        self.mock_crud_keys.create = AsyncMock()

        data = HieraKeyPost(key_model_id="dynamic:test")
        mock_request = MagicMock()
        await self.controller.create(
            request=mock_request, data=data, key_id="key1", fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_KEYS_CREATE
        )
        self.mock_crud_keys.create.assert_called_once()

    def _wire_key_model(self, model_id="dynamic:new", validate_side_effect=None):
        """Register a real key model in pyhiera whose validate() we control.

        NOTE: the controller reads ``pyhiera.hiera.key_models`` (snake_case).
        The previous version of this test set ``keyModels`` (camelCase), which
        because of MagicMock auto-vivification silently passed validation
        without ever exercising it. We use a real dict here so the cascade is
        actually driven.
        """
        instance = MagicMock()
        instance.validate = MagicMock(side_effect=validate_side_effect)
        model_type = MagicMock(return_value=instance)
        self.mock_pyhiera.hiera.key_models = {model_id: model_type}
        return model_type, instance

    async def test_update_new_model_revalidates_all_level_data(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        self.mock_crud_dynamic.get = AsyncMock()  # new model exists
        _, instance = self._wire_key_model("dynamic:new")

        level_data = MagicMock()
        level_data.result = [
            MagicMock(data={"foo": "bar"}),
            MagicMock(data={"baz": "qux"}),
        ]
        self.mock_crud_level_data.search = AsyncMock(return_value=level_data)
        self.mock_crud_keys.update = AsyncMock()

        data = HieraKeyPut(key_model_id="dynamic:new")
        await self.controller.update(
            request=MagicMock(), data=data, key_id="key1", fields=set()
        )

        # every existing level_data row must be re-validated against the new model
        self.mock_crud_level_data.search.assert_called_once()
        self.assertEqual(instance.validate.call_count, 2)
        self.mock_crud_keys.update.assert_called_once()

    async def test_update_new_model_invalid_data_raises_422(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        self.mock_crud_dynamic.get = AsyncMock()
        self._wire_key_model("dynamic:new", validate_side_effect=ValueError("nope"))

        level_data = MagicMock()
        level_data.result = [MagicMock(data={"foo": "bar"})]
        self.mock_crud_level_data.search = AsyncMock(return_value=level_data)
        self.mock_crud_keys.update = AsyncMock()

        from pyppetdb.errors import QueryParamValidationError

        data = HieraKeyPut(key_model_id="dynamic:new")
        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.controller.update(
                request=MagicMock(), data=data, key_id="key1", fields=set()
            )
        self.assertEqual(ctx.exception.status_code, 422)
        # existing data does not fit the new model -> the key must NOT be updated
        self.mock_crud_keys.update.assert_not_called()

    async def test_update_new_model_unknown_to_pyhiera_raises_422(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        self.mock_crud_dynamic.get = AsyncMock()  # exists in crud ...
        self.mock_pyhiera.hiera.key_models = {}  # ... but not registered in pyhiera

        level_data = MagicMock()
        level_data.result = [MagicMock(data={"foo": "bar"})]
        self.mock_crud_level_data.search = AsyncMock(return_value=level_data)
        self.mock_crud_keys.update = AsyncMock()

        from pyppetdb.errors import QueryParamValidationError

        data = HieraKeyPut(key_model_id="dynamic:new")
        with self.assertRaises(QueryParamValidationError):
            await self.controller.update(
                request=MagicMock(), data=data, key_id="key1", fields=set()
            )
        self.mock_crud_keys.update.assert_not_called()

    async def test_update_new_model_missing_raises_before_cascade(self):
        from pyppetdb.errors import ResourceNotFound

        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        # new model does not exist at all -> _key_model_exists raises
        self.mock_crud_dynamic.get = AsyncMock(side_effect=ResourceNotFound())
        self.mock_crud_level_data.search = AsyncMock()
        self.mock_crud_keys.update = AsyncMock()

        data = HieraKeyPut(key_model_id="dynamic:new")
        with self.assertRaises(ResourceNotFound):
            await self.controller.update(
                request=MagicMock(), data=data, key_id="key1", fields=set()
            )
        # must fail before touching level_data or updating the key
        self.mock_crud_level_data.search.assert_not_called()
        self.mock_crud_keys.update.assert_not_called()

    async def test_update_same_model_skips_revalidation(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:new")
        )
        self.mock_crud_dynamic.get = AsyncMock()  # model still validated for existence
        self._wire_key_model("dynamic:new")
        self.mock_crud_level_data.search = AsyncMock()
        self.mock_crud_keys.update = AsyncMock()

        data = HieraKeyPut(key_model_id="dynamic:new")
        await self.controller.update(
            request=MagicMock(), data=data, key_id="key1", fields=set()
        )
        # unchanged model -> no expensive re-validation of existing level data
        self.mock_crud_level_data.search.assert_not_called()
        self.mock_crud_keys.update.assert_called_once()

    async def test_update_without_model_skips_model_logic(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock(
            return_value=MagicMock(key_model_id="dynamic:old")
        )
        self.mock_crud_dynamic.get = AsyncMock()
        self.mock_crud_static.get = AsyncMock()
        self.mock_crud_level_data.search = AsyncMock()
        self.mock_crud_keys.update = AsyncMock()

        data = HieraKeyPut(description="just a description")
        await self.controller.update(
            request=MagicMock(), data=data, key_id="key1", fields=set()
        )
        # no key_model_id in payload -> neither existence check nor cascade
        self.mock_crud_dynamic.get.assert_not_called()
        self.mock_crud_static.get.assert_not_called()
        self.mock_crud_level_data.search.assert_not_called()
        self.mock_crud_keys.update.assert_called_once()

    async def test_delete_key(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.delete = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, key_id="key1")

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_KEYS_DELETE
        )
        self.mock_crud_keys.delete.assert_called_once_with(_id="key1")
        self.mock_crud_teams.drop_permissions_by_pattern.assert_called_once()

    async def test_delete_key_escapes_regex_metacharacters(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.delete = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, key_id=".*")

        pattern = self.mock_crud_teams.drop_permissions_by_pattern.call_args.kwargs[
            "pattern"
        ]
        self.assertIn(re.escape(".*"), pattern)
        self.assertNotIn("^HIERA:LEVEL_DATA:.*:", pattern)

    async def test_get_key(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_keys.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(request=mock_request, key_id="key1", fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_GET
        )
        self.mock_crud_keys.get.assert_called_once()

    async def test_search_keys(self):
        self.mock_authorize.require_perm = AsyncMock()
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

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_HIERA_GET
        )
        self.mock_crud_keys.search.assert_called_once()
