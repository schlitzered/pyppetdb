import logging
import re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.config import Config
from pyppetdb.model.common import DataDelete
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.model.jobs_jobs import (
    JobGet,
    JobGetMulti,
    JobPost,
)


class ControllerApiV1JobsJobs:

    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        authorize: AuthorizePyppetDB,
        crud_jobs: CrudJobs,
        crud_jobs_definitions: CrudJobsDefinitions,
        crud_nodes: CrudNodes,
        crud_jobs_node_jobs: CrudJobsNodeJobs,
    ):
        self._authorize = authorize
        self._config = config
        self._crud_jobs = crud_jobs
        self._crud_jobs_definitions = crud_jobs_definitions
        self._crud_nodes = crud_nodes
        self._crud_jobs_node_jobs = crud_jobs_node_jobs
        self._log = log
        self._router = APIRouter(
            prefix="/jobs/jobs",
            tags=["jobs"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=JobGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "",
            self.create,
            response_model=JobGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{job_id}",
            self.get,
            response_model=JobGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{job_id}/cancel",
            self.cancel,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["POST"],
        )

    @property
    def router(self):
        return self._router

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_jobs(self):
        return self._crud_jobs

    @property
    def crud_jobs_definitions(self):
        return self._crud_jobs_definitions

    async def search(
        self,
        request: Request,
        _id: str = Query(default=None),
        definition_id: str = Query(default=None),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs.search(
            _id=_id,
            definition_id=definition_id,
            fields=[],
            page=page,
            limit=limit,
        )

    async def get(self, request: Request, job_id: str):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs.get(
            _id=job_id,
            fields=[],
        )

    async def create(self, request: Request, data: JobPost):
        user = await self.authorize.require_admin(request=request)

        definition = await self.crud_jobs_definitions.get(
            _id=data.definition_id,
            fields=[],
        )

        self._validate_params(
            values=data.parameters,
            definitions=definition.params,
            context="parameter",
        )

        self._validate_params(
            values=data.env_vars,
            definitions=definition.environment_variables,
            context="environment variable",
        )

        limit = self._config.jobs.maxNodesPerJob
        count = await self._crud_nodes.count(fact=data.node_filter)

        if count > limit:
            raise HTTPException(
                status_code=400,
                detail=f"Too many nodes selected (max: {limit}, selected: {count})",
            )

        nodes_result = await self._crud_nodes.search(
            fact=data.node_filter,
            fields=["id"],
            limit=limit,
        )
        node_ids = [node.id for node in nodes_result.result if node.id]

        job = await self._crud_jobs.create(
            payload=data,
            node_ids=node_ids,
            created_by=user.id,
            fields=[],
        )

        # Create NodeJob entries for each node
        await self._crud_jobs_node_jobs.create_node_jobs(
            job_id=job.id,
            node_ids=node_ids,
        )

        return job

    async def cancel(self, request: Request, job_id: str):
        await self.authorize.require_admin(request=request)
        await self._crud_jobs_node_jobs.cancel_node_jobs(job_id=job_id)
        return DataDelete()

    @staticmethod
    def _validate_params(
        values: Dict[str, Any], definitions: Dict[str, Any], context: str
    ):
        for key in definitions:
            if key not in values:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing {context}: {key}",
                )

        for key, val in values.items():
            if key not in definitions:
                raise HTTPException(status_code=400, detail=f"Unknown {context}: {key}")

            defn = definitions[key]
            val_type = defn.type

            if val_type == "string":
                if not isinstance(val, str):
                    raise HTTPException(
                        status_code=400, detail=f"{context} {key} must be a string"
                    )
                if defn.regex and not re.match(defn.regex, val):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{context} {key} does not match regex: {defn.regex}",
                    )

            elif val_type in ("int", "float"):
                if val_type == "int" and not isinstance(val, int):
                    raise HTTPException(
                        status_code=400, detail=f"{context} {key} must be an integer"
                    )
                if val_type == "float" and not isinstance(val, (int, float)):
                    raise HTTPException(
                        status_code=400, detail=f"{context} {key} must be a number"
                    )

                if defn.min is not None and val < defn.min:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{context} {key} must be at least {defn.min}",
                    )
                if defn.max is not None and val > defn.max:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{context} {key} must be at most {defn.max}",
                    )

            elif val_type == "bool":
                if not isinstance(val, bool):
                    raise HTTPException(
                        status_code=400, detail=f"{context} {key} must be a boolean"
                    )

            elif val_type == "enum":
                if defn.options and val not in defn.options:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{context} {key} must be one of: {', '.join(defn.options)}",
                    )
