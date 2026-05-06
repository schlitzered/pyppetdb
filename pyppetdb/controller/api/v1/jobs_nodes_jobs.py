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

import logging
from typing import Any, Set
from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs

from pyppetdb.model.jobs_nodes_jobs import NodeJobGet
from pyppetdb.model.jobs_nodes_jobs import JobsNodeJobGetMulti
from pyppetdb.model.jobs_nodes_jobs import filter_list
from pyppetdb.model.jobs_nodes_jobs import filter_literal


class ControllerApiV1JobsNodesJobs:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_jobs_node_jobs: CrudJobsNodeJobs,
        manager: Any,
    ):
        self._authorize = authorize
        self._crud_jobs_node_jobs = crud_jobs_node_jobs
        self._manager = manager
        self._log = log
        self._router = APIRouter(
            prefix="/jobs/nodes_jobs",
            tags=["jobs_nodes_jobs"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=JobsNodeJobGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{node_job_id}",
            self.get,
            response_model=NodeJobGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def router(self):
        return self._router

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_jobs_nodes_jobs(self):
        return self._crud_jobs_node_jobs

    async def search(
        self,
        request: Request,
        job_id: str = Query(default=None),
        node_id: str = Query(default=None),
        status: str = Query(default=None),
        fields: Set[filter_literal] = Query(default=filter_list),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_perm(request=request, permission=PERM_JOBS_GET)
        result = await self.crud_jobs_nodes_jobs.search(
            job_id=job_id,
            node_id=node_id,
            status=status,
            fields=list(fields),
            page=page,
            limit=limit,
        )

        for job in result.result:
            chunks = await self._manager.get_log_chunks(
                job_run_id=job.id,
            )
            job.log_blobs = [f"{job.id}:{chunk}" for chunk in chunks]

        return result

    async def get(
        self,
        request: Request,
        node_job_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_perm(request=request, permission=PERM_JOBS_GET)
        job = await self.crud_jobs_nodes_jobs.get(
            _id=node_job_id,
            fields=list(fields),
        )

        chunks = await self._manager.get_log_chunks(
            job_run_id=node_job_id,
        )
        job.log_blobs = [f"{node_job_id}:{chunk}" for chunk in chunks]

        return job
