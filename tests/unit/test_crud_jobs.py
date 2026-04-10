import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.model.jobs_jobs import JobPost


class TestCrudJobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudJobs(
            self.log,
            self.mock_config,
            self.mock_coll,
        )

    async def test_create_job(self):
        # Setup mocks
        self.crud._create = AsyncMock(
            return_value={
                "id": "job1",
                "definition_id": "def1",
                "parameters": {},
                "env_vars": {},
                "node_filter": ["kernel:eq:str:Linux"],
                "nodes": ["node1"],
                "created_by": "admin",
                "created_at": datetime.now(),
            }
        )

        payload = JobPost(definition_id="def1", node_filter={"kernel:eq:str:Linux"})

        result = await self.crud.create(
            payload=payload,
            node_ids=["node1"],
            created_by="admin",
            fields=[],
        )

        self.assertEqual(result.id, "job1")
        self.assertEqual(result.nodes, ["node1"])
