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
from typing import Set

from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_CREATE
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_DELETE
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGet
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGetMulti
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorPost
from pyppetdb.model.nodes_secrets_redactor import filter_list
from pyppetdb.model.nodes_secrets_redactor import filter_literal
from pyppetdb.model.nodes_secrets_redactor import sort_literal


class ControllerApiV1NodesSecretsRedactor:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes_secrets_redactor: CrudNodesSecretsRedactor,
    ):
        self._authorize = authorize
        self._crud_nodes_secrets_redactor = crud_nodes_secrets_redactor
        self._log = log
        self._router = APIRouter(
            prefix="/nodes_secrets_redactor",
            tags=["nodes_secrets_redactor"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodesSecretsRedactorGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "",
            self.create,
            response_model=NodesSecretsRedactorGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{secret_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def router(self):
        return self._router

    async def create(self, request: Request, payload: NodesSecretsRedactorPost):
        await self.authorize.require_perm(
            request=request, permission=PERM_NODES_SECRETS_REDACTOR_CREATE
        )
        return await self._crud_nodes_secrets_redactor.create(payload=payload)

    async def delete(self, request: Request, secret_id: str):
        await self.authorize.require_perm(
            request=request, permission=PERM_NODES_SECRETS_REDACTOR_DELETE
        )
        return await self._crud_nodes_secrets_redactor.delete(_id=secret_id)

    async def search(
        self,
        request: Request,
        secret_id: str = Query(description="filter: regular_expressions", default=None),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="id"),
        sort_order: sort_order_literal = Query(default="ascending"),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_user(request=request)
        return await self._crud_nodes_secrets_redactor.search(
            _id=secret_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
