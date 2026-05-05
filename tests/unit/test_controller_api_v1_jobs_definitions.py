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
from fastapi import HTTPException, Request
from pyppetdb.controller.api.v1.jobs_definitions import ControllerApiV1JobsDefinitions
from pyppetdb.model.jobs_definitions import (
    JobDefinitionPost,
    JobDefinitionPut,
    JobParamDefinition,
)


class TestControllerApiV1JobsDefinitionsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.controller = ControllerApiV1JobsDefinitions(
            log=self.log,
            authorize=self.mock_authorize,
            crud_jobs_definitions=self.mock_crud,
            crud_teams=self.mock_crud_teams,
        )

    async def test_create_validation_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()

        payload = JobDefinitionPost(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{path}", "{options}"],
            params={
                "path": JobParamDefinition(type="string"),
                "options": JobParamDefinition(type="string"),
            },
        )
        self.mock_crud.create = AsyncMock(return_value={"id": "def1"})

        await self.controller.create(request=mock_request, data=payload)
        self.mock_crud.create.assert_called_once()

    async def test_create_validation_missing_param(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()

        payload = JobDefinitionPost(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{path}", "{options}"],
            params={"path": JobParamDefinition(type="string")},
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Missing parameters for template: options", cm.exception.detail)

    async def test_create_validation_extra_param(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()

        payload = JobDefinitionPost(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{path}"],
            params={
                "path": JobParamDefinition(type="string"),
                "extra": JobParamDefinition(type="string"),
            },
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Extra parameters not in template: extra", cm.exception.detail)

    async def test_update_validation_success_partial_template(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()

        # Mock existing
        mock_existing = MagicMock()
        mock_existing.params_template = "{path}"
        mock_existing.params = {"path": JobParamDefinition(type="string")}
        self.mock_crud.get = AsyncMock(return_value=mock_existing)
        self.mock_crud.update = AsyncMock()

        # Update only template, should match existing params
        payload = JobDefinitionPut(params_template=["{path}"])

        await self.controller.update(
            request=mock_request, definition_id="def1", data=payload
        )
        self.mock_crud.update.assert_called_once()

    async def test_update_validation_failure_partial_template(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()

        # Mock existing
        mock_existing = MagicMock()
        mock_existing.params_template = "{path}"
        mock_existing.params = {"path": JobParamDefinition(type="string")}
        self.mock_crud.get = AsyncMock(return_value=mock_existing)

        # Update template to something that needs more params than existing
        payload = JobDefinitionPut(params_template=["{path}", "{new_one}"])

        with self.assertRaises(HTTPException) as cm:
            await self.controller.update(
                request=mock_request, definition_id="def1", data=payload
            )
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Missing parameters for template: new_one", cm.exception.detail)
