import logging
from fastapi import APIRouter
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.jobs_nodes_jobs_logs import CrudJobsNodesLogsLogBlobs
from pyppetdb.model.jobs_nodes_jobs_logs import LogBlobGet


class ControllerApiV1JobsNodesJobsLogs:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_jobs_nodes_jobs_log_blobs: CrudJobsNodesLogsLogBlobs,
    ):
        self._authorize = authorize
        self._crud_jobs_nodes_jobs_log_blobs = crud_jobs_nodes_jobs_log_blobs
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

    @property
    def crud_jobs_nodes_jobs_log_blobs(self):
        return self._crud_jobs_nodes_jobs_log_blobs

    async def get(self, request: Request, log_id: str):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs_nodes_jobs_log_blobs.get(_id=log_id, fields=[])
