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
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_CA_SPACES_CREATE
from pyppetdb.authorize import PERM_CA_SPACES_UPDATE
from pyppetdb.authorize import PERM_CA_SPACES_DELETE
from pyppetdb.authorize import PATTERN_CA_SPACES
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.ca_spaces import CASpacePut
from pyppetdb.model.ca_spaces import filter_literal
from pyppetdb.model.ca_spaces import filter_list
from pyppetdb.model.ca_spaces import sort_literal
from pyppetdb.model.common import sort_order_literal
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.ca.validation_protector import CAValidationProtector


class ControllerApiV1CASpaces:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_ca_spaces: CrudCASpaces,
        crud_ca_authorities: CrudCAAuthorities,
        crud_ca_certificates: CrudCACertificates,
        crud_teams: CrudTeams,
        ca_service: CAService,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_ca_spaces = crud_ca_spaces
        self._crud_ca_authorities = crud_ca_authorities
        self._crud_ca_certificates = crud_ca_certificates
        self._crud_teams = crud_teams
        self._ca_service = ca_service
        self._router = APIRouter(prefix="/ca/spaces", tags=["ca spaces"])

        self._router.add_api_route(
            "",
            self.search,
            methods=["GET"],
            response_model=CASpaceGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.create,
            methods=["POST"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.get,
            methods=["GET"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.update,
            methods=["PUT"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.delete,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

    def _mask(self, data: CASpaceGet):
        if data.validation_config:
            protector = CAValidationProtector(protector=None)
            data.validation_config = protector.mask_config(data.validation_config)
        return data

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_ca_spaces(self):
        return self._crud_ca_spaces

    @property
    def crud_ca_authorities(self):
        return self._crud_ca_authorities

    @property
    def crud_ca_certificates(self):
        return self._crud_ca_certificates

    async def update(
        self,
        request: Request,
        space_id: str,
        data: CASpacePut,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_perm(
            request=request, permission=PERM_CA_SPACES_UPDATE
        )
        if data.ca_id:
            await self.crud_ca_authorities.get(data.ca_id, fields=["id"])
        res = await self._ca_service.update_space(
            _id=space_id, payload=data, fields=list(fields)
        )
        return self._mask(res)

    async def create(
        self,
        request: Request,
        space_id: str,
        data: CASpacePost,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_perm(
            request=request, permission=PERM_CA_SPACES_CREATE
        )
        res = await self._ca_service.create_space(
            _id=space_id, payload=data, fields=list(fields)
        )
        return self._mask(res)

    async def get(
        self,
        request: Request,
        space_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_perm(request=request, permission=PERM_CA_GET)
        res = await self.crud_ca_spaces.get(_id=space_id, fields=list(fields))
        return self._mask(res)

    async def delete(
        self,
        request: Request,
        space_id: str,
    ):
        await self.authorize.require_perm(
            request=request, permission=PERM_CA_SPACES_DELETE
        )

        count = await self.crud_ca_certificates.count({"space_id": space_id})
        if count > 0:
            raise QueryParamValidationError(
                msg=f"CA Space '{space_id}' still contains certificates"
            )

        await self._ca_service.delete_space(_id=space_id)
        await self._crud_teams.drop_permissions_by_pattern(
            PATTERN_CA_SPACES.format(space_id=space_id)
        )
        return {}

    async def search(
        self,
        request: Request,
        space_id: str = Query(description="filter: regular_expressions", default=None),
        ca_id: str = Query(description="filter: regular_expressions", default=None),
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
        await self.authorize.require_perm(request=request, permission=PERM_CA_GET)
        res = await self.crud_ca_spaces.search(
            _id=space_id,
            ca_id=ca_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        for r in res.result:
            self._mask(r)
        return res
