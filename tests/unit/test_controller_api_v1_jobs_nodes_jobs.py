import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from fastapi import Request
from pyppetdb.controller.api.v1.jobs_nodes_jobs import ControllerApiV1JobsNodesJobs


class TestControllerApiV1JobsNodesJobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud = MagicMock()
        self.controller = ControllerApiV1JobsNodesJobs(
            log=self.log,
            authorize=self.mock_authorize,
            crud_jobs_node_jobs=self.mock_crud,
        )

    async def test_get_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_user = AsyncMock()
        self.mock_crud.get = AsyncMock(return_value={"id": "job1:node1"})

        result = await self.controller.get(
            request=mock_request, node_job_id="job1:node1"
        )

        self.mock_authorize.require_user.assert_called_once()
        self.mock_crud.get.assert_called_once_with(
            _id="job1:node1",
            fields=[],
        )
        self.assertEqual(result, {"id": "job1:node1"})

    async def test_search_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_user = AsyncMock()
        self.mock_crud.search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )

        await self.controller.search(
            request=mock_request,
            job_id="job1",
            node_id="node1",
            status="scheduled",
            page=0,
            limit=10,
        )

        self.mock_authorize.require_user.assert_called_once()
        self.mock_crud.search.assert_called_once_with(
            job_id="job1",
            node_id="node1",
            status="scheduled",
            fields=[],
            page=0,
            limit=10,
        )
