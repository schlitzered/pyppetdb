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
import re
from typing import List, Set

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.authorize import PERM_JOBS_DEFINITION_CREATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_UPDATE
from pyppetdb.authorize import PERM_JOBS_DEFINITION_DELETE
from pyppetdb.authorize import PATTERN_JOBS_JOB
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.model.jobs_definitions import JobDefinitionGet
from pyppetdb.model.jobs_definitions import JobDefinitionGetMulti
from pyppetdb.model.jobs_definitions import JobDefinitionPost
from pyppetdb.model.jobs_definitions import JobDefinitionPut
from pyppetdb.model.jobs_definitions import filter_list
from pyppetdb.model.jobs_definitions import filter_literal
from pyppetdb.model.common import DataDelete


class ControllerApiV1JobsDefinitions:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_jobs_definitions: CrudJobsDefinitions,
        crud_teams: CrudTeams,
    ):
        self._authorize = authorize
        self._crud_jobs_definitions = crud_jobs_definitions
        self._crud_teams = crud_teams
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
        fields: Set[filter_literal] = Query(default=filter_list),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_perm(request=request, permission=PERM_JOBS_GET)
        return await self.crud_jobs_definitions.search(
            _id=_id,
            fields=list(fields),
            page=page,
            limit=limit,
        )

    async def get(
        self,
        request: Request,
        definition_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_perm(request=request, permission=PERM_JOBS_GET)
        return await self.crud_jobs_definitions.get(
            _id=definition_id, fields=list(fields)
        )

    async def create(self, request: Request, data: JobDefinitionPost):
        await self.authorize.require_perm(
            request=request, permission=PERM_JOBS_DEFINITION_CREATE
        )

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
        await self.authorize.require_perm(
            request=request, permission=PERM_JOBS_DEFINITION_UPDATE
        )

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
        await self.authorize.require_perm(
            request=request, permission=PERM_JOBS_DEFINITION_DELETE
        )
        result = await self.crud_jobs_definitions.delete(_id=definition_id)
        await self._crud_teams.drop_permissions_by_pattern(
            pattern=f"{PATTERN_JOBS_JOB.format(definition_id=definition_id)}CREATE$"
        )
        return result

    def _validate_params_template(self, params_template: List[str], params: dict):
        placeholders = set()
        for token in params_template:
            matches = re.findall(r"\{(.*?)\}", token)
            for m in matches:
                placeholders.add(m)

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
