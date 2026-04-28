import unittest
import datetime
from unittest.mock import MagicMock, AsyncMock
import logging
from fastapi import Request
from pyppetdb.controller.api.v1.jobs_nodes_jobs import ControllerApiV1JobsNodesJobs
from pyppetdb.model.jobs_nodes_jobs import NodeJobGet, JobsNodeJobGetMulti


class TestControllerApiV1JobsNodesJobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud = MagicMock()
        self.mock_manager = MagicMock()
        self.controller = ControllerApiV1JobsNodesJobs(
            log=self.log,
            authorize=self.mock_authorize,
            crud_jobs_node_jobs=self.mock_crud,
            manager=self.mock_manager,
        )

    async def test_get_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_user = AsyncMock()
        mock_job = NodeJobGet(
            id="job1:node1",
            job_id="job1",
            definition_id="def1",
            node_id="node1",
            status="running",
            created_by="admin",
            created_at=datetime.datetime.now(),
            log_blobs=[],
        )
        self.mock_crud.get = AsyncMock(return_value=mock_job)
        self.mock_manager.get_log_chunks = AsyncMock(return_value=["chunk1"])

        result = await self.controller.get(
            request=mock_request,
            node_job_id="job1:node1",
        )

        self.mock_authorize.require_user.assert_called_once()
        self.mock_crud.get.assert_called_once_with(
            _id="job1:node1",
            fields=[],
        )
        self.mock_manager.get_log_chunks.assert_called_once_with(
            job_run_id="job1:node1",
        )
        self.assertEqual(result.id, "job1:node1")
        self.assertEqual(result.log_blobs, ["job1:node1:chunk1"])

    async def test_search_success(self):
        mock_request = MagicMock(spec=Request)
        self.mock_authorize.require_user = AsyncMock()
        mock_job = NodeJobGet(
            id="job1:node1",
            job_id="job1",
            definition_id="def1",
            node_id="node1",
            status="running",
            created_by="admin",
            created_at=datetime.datetime.now(),
            log_blobs=[],
        )
        self.mock_crud.search = AsyncMock(
            return_value=JobsNodeJobGetMulti(
                result=[mock_job], meta={"result_size": 1, "page": 0, "limit": 10}
            )
        )
        self.mock_manager.get_log_chunks = AsyncMock(return_value=["chunk1"])

        result = await self.controller.search(
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
        self.mock_manager.get_log_chunks.assert_called_once_with(
            job_run_id="job1:node1",
        )
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].log_blobs, ["job1:node1:chunk1"])
