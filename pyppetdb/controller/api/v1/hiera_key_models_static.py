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
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_HIERA_GET
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models_static import filter_list
from pyppetdb.model.hiera_key_models_static import filter_literal
from pyppetdb.model.hiera_key_models_static import sort_literal
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGet
from pyppetdb.model.hiera_key_models_static import HieraKeyModelGetMulti


class ControllerApiV1HieraKeyModelsStatic:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models_static = crud_hiera_key_models_static
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/key_models/static",
            tags=["hiera_key_models_static"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=HieraKeyModelGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{key_model_id}",
            self.get,
            response_model=HieraKeyModelGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def log(self):
        return self._log

    @property
    def crud_hiera_key_models_static(self):
        return self._crud_hiera_key_models_static

    @property
    def router(self):
        return self._router

    async def search(
        self,
        request: Request,
        key_model_id: str = Query(
            description="filter: regular_expressions", default=None
        ),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="id"),
        sort_order: sort_order_literal = Query(default="ascending"),
        page: int = Query(default=0, ge=0, description="pagination index"),
        limit: int = Query(
            default=10,
            ge=10,
            le=1000,
            description="pagination limit, min value 10, max value 1000",
        ),
    ):
        await self._authorize.require_perm(request=request, permission=PERM_HIERA_GET)

        result = await self.crud_hiera_key_models_static.search(
            _id=key_model_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return result

    async def get(
        self,
        request: Request,
        key_model_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_perm(request=request, permission=PERM_HIERA_GET)

        result = await self.crud_hiera_key_models_static.get(
            _id=key_model_id,
            fields=list(fields),
        )
        return result
