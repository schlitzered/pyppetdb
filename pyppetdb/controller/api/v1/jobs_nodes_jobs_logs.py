import logging
from typing import Any
from fastapi import APIRouter
from fastapi import Request, HTTPException

from pyppetdb.authorize import AuthorizePyppetDB
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
        await self.authorize.require_user(request=request)

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
