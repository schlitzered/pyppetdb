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
from pyppetdb.controller.api.v1.jobs_jobs import ControllerApiV1JobsJobs
from pyppetdb.model.jobs_jobs import JobPost, JobGetMulti
from pyppetdb.model.jobs_definitions import JobDefinitionGet
from pyppetdb.authorize import (
    PERM_JOBS_GET,
    PERM_JOBS_JOB_CREATE,
    PERM_JOBS_JOB_CREATE_DYNAMIC,
)


class TestControllerApiV1JobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.jobs.maxNodesPerJob = 1000
        self.mock_crud_definitions = MagicMock()
        self.mock_crud_jobs = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_node_jobs = MagicMock()
        self.controller = ControllerApiV1JobsJobs(
            log=self.log,
            config=self.mock_config,
            authorize=self.mock_authorize,
            crud_jobs_definitions=self.mock_crud_definitions,
            crud_jobs=self.mock_crud_jobs,
            crud_nodes=self.mock_crud_nodes,
            crud_jobs_node_jobs=self.mock_crud_node_jobs,
        )

    async def test_jobs_create_validation_success(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)

        # Mock definition
        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{{path}}"],
            params={"path": {"type": "string", "regex": "^/tmp/.*"}},
            environment_variables={"RETRIES": {"type": "int", "min": 1, "max": 5}},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        # Mock count and nodes result
        self.mock_crud_nodes.count = AsyncMock(return_value=1)
        mock_node = MagicMock()
        mock_node.id = "node1"
        nodes_result = MagicMock()
        nodes_result.result = [mock_node]
        self.mock_crud_nodes.search = AsyncMock(return_value=nodes_result)
        mock_job = MagicMock()
        mock_job.id = "job1"
        self.mock_crud_jobs.create = AsyncMock(return_value=mock_job)
        self.mock_crud_node_jobs.create_node_jobs = AsyncMock()
        self.mock_crud_node_jobs.get_busy_nodes_for_definition = AsyncMock(
            return_value=[]
        )

        payload = JobPost(
            definition_id="def1",
            parameters={"path": "/tmp/test"},
            env_vars={"RETRIES": 3},
            node_filter={"kernel:eq:str:Linux"},
        )

        await self.controller.create(
            request=mock_request,
            data=payload,
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=[
                PERM_JOBS_JOB_CREATE,
                PERM_JOBS_JOB_CREATE_DYNAMIC.format(definition_id="def1"),
            ],
        )

        self.mock_crud_nodes.search.assert_called_once()
        self.mock_crud_node_jobs.get_busy_nodes_for_definition.assert_called_once_with(
            definition_id="def1",
            node_ids=["node1"],
        )
        self.mock_crud_jobs.create.assert_called_once_with(
            payload=payload,
            node_ids=["node1"],
            created_by="admin",
            fields=[],
        )
        self.mock_crud_node_jobs.create_node_jobs.assert_called_once_with(
            job_id="job1",
            definition_id="def1",
            node_ids=["node1"],
            created_by="admin",
        )

    async def test_jobs_create_filters_busy_nodes(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)

        # Mock definition
        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=[],
            params={},
            environment_variables={},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        # Mock nodes: node1 and node2
        self.mock_crud_nodes.count = AsyncMock(return_value=2)
        mock_node1 = MagicMock()
        mock_node1.id = "node1"
        mock_node2 = MagicMock()
        mock_node2.id = "node2"
        nodes_result = MagicMock()
        nodes_result.result = [mock_node1, mock_node2]
        self.mock_crud_nodes.search = AsyncMock(return_value=nodes_result)

        # Mock node1 as busy
        self.mock_crud_node_jobs.get_busy_nodes_for_definition = AsyncMock(
            return_value=["node1"]
        )

        mock_job = MagicMock()
        mock_job.id = "job1"
        self.mock_crud_jobs.create = AsyncMock(return_value=mock_job)
        self.mock_crud_node_jobs.create_node_jobs = AsyncMock()

        payload = JobPost(
            definition_id="def1",
            node_filter={"kernel:eq:str:Linux"},
        )

        await self.controller.create(request=mock_request, data=payload)

        # Only node2 should be in the job targets
        self.mock_crud_jobs.create.assert_called_once_with(
            payload=payload,
            node_ids=["node2"],
            created_by="admin",
            fields=[],
        )
        self.mock_crud_node_jobs.create_node_jobs.assert_called_once_with(
            job_id="job1",
            definition_id="def1",
            node_ids=["node2"],
            created_by="admin",
        )

    async def test_jobs_cancel_success(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)
        self.mock_crud_node_jobs.cancel_node_jobs = AsyncMock()

        mock_job = MagicMock()
        mock_job.definition_id = "def1"
        self.mock_crud_jobs.get = AsyncMock(return_value=mock_job)

        await self.controller.cancel(
            request=mock_request,
            job_id="job1",
        )

        self.mock_crud_jobs.get.assert_called_once_with(
            _id="job1", fields=["definition_id"]
        )
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=[
                PERM_JOBS_JOB_CREATE,
                PERM_JOBS_JOB_CREATE_DYNAMIC.format(definition_id="def1"),
            ],
        )
        self.mock_crud_node_jobs.cancel_node_jobs.assert_called_once_with(job_id="job1")

    async def test_jobs_create_too_many_nodes(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)
        self.mock_config.jobs.maxNodesPerJob = 2

        # Mock definition
        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=[],
            params={},
            environment_variables={},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        # Mock count returning 3 nodes (more than limit 2)
        self.mock_crud_nodes.count = AsyncMock(return_value=3)

        payload = JobPost(
            definition_id="def1",
            node_filter={"kernel:eq:str:Linux"},
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn(
            "Too many nodes selected (max: 2, selected: 3)", cm.exception.detail
        )

    async def test_jobs_create_missing_params(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)

        # Mock definition with 'path' required
        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{path}"],
            params={"path": {"type": "string"}},
            environment_variables={},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        # payload missing 'path' in parameters
        payload = JobPost(
            definition_id="def1",
            parameters={},
            node_filter={"kernel:eq:str:Linux"},
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Missing parameter: path", cm.exception.detail)

    async def test_jobs_create_validation_failure_regex(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)

        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=["{{path}}"],
            params={"path": {"type": "string", "regex": "^/tmp/.*"}},
            environment_variables={},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        payload = JobPost(
            definition_id="def1",
            parameters={"path": "/etc/passwd"},
            node_filter={"kernel:eq:str:Linux"},
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("does not match regex", cm.exception.detail)

    async def test_jobs_create_validation_failure_bounds(self):
        mock_request = MagicMock(spec=Request)
        mock_user = MagicMock()
        mock_user.id = "admin"
        self.mock_authorize.require_perm = AsyncMock(return_value=mock_user)

        mock_def = JobDefinitionGet(
            id="def1",
            executable="/bin/ls",
            user="root",
            group="root",
            params_template=[],
            params={},
            environment_variables={"RETRIES": {"type": "int", "min": 1, "max": 5}},
        )
        self.mock_crud_definitions.get = AsyncMock(return_value=mock_def)

        payload = JobPost(
            definition_id="def1",
            env_vars={"RETRIES": 10},
            node_filter={"kernel:eq:str:Linux"},
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.create(request=mock_request, data=payload)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("must be at most 5", cm.exception.detail)

    async def test_jobs_search_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_jobs.search = AsyncMock(
            return_value=JobGetMulti(result=[], meta={"result_size": 0})
        )

        await self.controller.search(
            request=mock_request,
            fields=set(),
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_JOBS_GET
        )
        self.mock_crud_jobs.search.assert_called_once()

    async def test_jobs_get_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_jobs.get = AsyncMock()

        await self.controller.get(
            request=mock_request,
            job_id="job1",
            fields=set(),
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_JOBS_GET
        )
        self.mock_crud_jobs.get.assert_called_once_with(_id="job1", fields=[])
