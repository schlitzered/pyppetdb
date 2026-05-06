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
from typing import Any
from fastapi import APIRouter
from fastapi import Request, HTTPException

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.model.jobs_nodes_jobs_logs import LogBlobGet


class ControllerApiV1JobsNodesJobsLogs:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        manager: Any,
    ):
        self._authorize = authorize
        self._manager = manager
        self._log = log
        self._router = APIRouter(
            prefix="/jobs/nodes_jobs_logs",
            tags=["jobs_nodes_jobs_logs"],
        )

        self.router.add_api_route(
            "/{log_id}",
            self.get,
            response_model=LogBlobGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def router(self):
        return self._router

    @property
    def authorize(self):
        return self._authorize

    async def get(
        self,
        request: Request,
        log_id: str,
    ):
        await self.authorize.require_perm(request=request, permission=PERM_JOBS_GET)

        try:
            job_run_id, chunk_id = log_id.rsplit(
                ":",
                1,
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid log_id format. Expected job_id:node_id:chunk_id",
            )

        data = await self._manager.get_log_chunk(
            job_run_id=job_run_id,
            chunk_id=chunk_id,
        )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="Log chunk not found or agent offline",
            )

        return LogBlobGet(
            id=log_id,
            data=data,
        )
