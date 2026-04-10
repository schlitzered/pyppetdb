import logging
from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.model.jobs_nodes_jobs import (
    NodeJobGet,
    JobsNodeJobGetMulti,
)


class ControllerApiV1JobsNodesJobs:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_jobs_node_jobs: CrudJobsNodeJobs,
    ):
        self._authorize = authorize
        self._crud_jobs_node_jobs = crud_jobs_node_jobs
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
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs_nodes_jobs.search(
            job_id=job_id,
            node_id=node_id,
            status=status,
            fields=[],
            page=page,
            limit=limit,
        )

    async def get(self, request: Request, node_job_id: str):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs_nodes_jobs.get(
            _id=node_job_id,
            fields=[],
        )
