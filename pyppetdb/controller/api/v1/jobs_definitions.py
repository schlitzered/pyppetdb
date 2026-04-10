import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.model.jobs_definitions import (
    JobDefinitionGet,
    JobDefinitionGetMulti,
    JobDefinitionPost,
    JobDefinitionPut,
)
from pyppetdb.model.common import DataDelete


class ControllerApiV1JobsDefinitions:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_jobs_definitions: CrudJobsDefinitions,
    ):
        self._authorize = authorize
        self._crud_jobs_definitions = crud_jobs_definitions
        self._log = log
        self._router = APIRouter(
            prefix="/jobs/definitions",
            tags=["jobs_definitions"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=JobDefinitionGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "",
            self.create,
            response_model=JobDefinitionGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{definition_id}",
            self.get,
            response_model=JobDefinitionGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{definition_id}",
            self.update,
            response_model=JobDefinitionGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )
        self.router.add_api_route(
            "/{definition_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )

    @property
    def router(self):
        return self._router

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_jobs_definitions(self):
        return self._crud_jobs_definitions

    async def search(
        self,
        request: Request,
        _id: str = Query(default=None),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs_definitions.search(
            _id=_id,
            fields=[],
            page=page,
            limit=limit,
        )

    async def get(self, request: Request, definition_id: str):
        await self.authorize.require_user(request=request)
        return await self.crud_jobs_definitions.get(_id=definition_id, fields=[])

    async def create(self, request: Request, data: JobDefinitionPost):
        await self.authorize.require_admin(request=request)

        self._validate_params_template(
            params_template=data.params_template,
            params=data.params,
        )

        return await self.crud_jobs_definitions.create(
            payload=data,
            fields=[],
        )

    async def update(
        self, request: Request, definition_id: str, data: JobDefinitionPut
    ):
        await self.authorize.require_admin(request=request)

        if data.params_template is not None or data.params is not None:
            existing = await self.crud_jobs_definitions.get(
                _id=definition_id,
                fields=[],
            )

            params_template = data.params_template
            if params_template is None:
                params_template = existing.params_template

            params = data.params
            if params is None:
                params = existing.params

            self._validate_params_template(
                params_template=params_template,
                params=params,
            )

        return await self.crud_jobs_definitions.update(
            _id=definition_id,
            payload=data,
            fields=[],
        )

    async def delete(self, request: Request, definition_id: str):
        await self.authorize.require_admin(request=request)
        return await self.crud_jobs_definitions.delete(_id=definition_id)

    def _validate_params_template(self, params_template: str, params: dict):
        placeholders = set(re.findall(r"\{(.*?)\}", params_template))
        param_names = set(params.keys())

        missing = placeholders - param_names
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing parameters for template: {', '.join(missing)}",
            )

        extra = param_names - placeholders
        if extra:
            raise HTTPException(
                status_code=400,
                detail=f"Extra parameters not in template: {', '.join(extra)}",
            )
