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
from typing import Set
from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_CA_SECRETS_CREATE
from pyppetdb.authorize import PERM_CA_SECRETS_UPDATE
from pyppetdb.authorize import PERM_CA_SECRETS_DELETE
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_secrets import CrudCASecrets
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.errors import ResourceInUse
from pyppetdb.model.ca_secrets import CA_SECRET_ID_PATTERN
from pyppetdb.model.ca_secrets import CASecretGet
from pyppetdb.model.ca_secrets import CASecretGetMulti
from pyppetdb.model.ca_secrets import CASecretPost
from pyppetdb.model.ca_secrets import CASecretPut
from pyppetdb.model.ca_secrets import filter_literal
from pyppetdb.model.ca_secrets import filter_list
from pyppetdb.model.ca_secrets import sort_literal
from pyppetdb.model.common import sort_order_literal

_RE_SECRET_ID = re.compile(CA_SECRET_ID_PATTERN)


class ControllerApiV1CASecrets:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_secrets: CrudCASecrets,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_secrets = crud_secrets
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._router = APIRouter(prefix="/ca/secrets", tags=["ca secrets"])

        self._router.add_api_route(
            "",
            self.search,
            methods=["GET"],
            response_model=CASecretGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{secret_id}",
            self.create,
            methods=["POST"],
            response_model=CASecretGet,
            response_model_exclude_unset=True,
            status_code=201,
        )
        self._router.add_api_route(
            "/{secret_id}",
            self.get,
            methods=["GET"],
            response_model=CASecretGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{secret_id}",
            self.update,
            methods=["PUT"],
            response_model=CASecretGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{secret_id}",
            self.delete,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

    @staticmethod
    def _validate_id(secret_id: str) -> None:
        if not _RE_SECRET_ID.match(secret_id):
            raise QueryParamValidationError(
                msg=(
                    "invalid secret id: only letters, digits, '_' and '-' are "
                    "allowed"
                )
            )

    async def create(
        self,
        request: Request,
        secret_id: str,
        data: CASecretPost,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_perm(
            request=request, permission=PERM_CA_SECRETS_CREATE
        )
        self._validate_id(secret_id)
        return await self._crud_secrets.create(
            _id=secret_id, payload=data, fields=list(fields)
        )

    async def update(
        self,
        request: Request,
        secret_id: str,
        data: CASecretPut,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_perm(
            request=request, permission=PERM_CA_SECRETS_UPDATE
        )
        return await self._crud_secrets.update(
            _id=secret_id, payload=data, fields=list(fields)
        )

    async def get(
        self,
        request: Request,
        secret_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_perm(request=request, permission=PERM_CA_GET)
        return await self._crud_secrets.get(_id=secret_id, fields=list(fields))

    async def delete(
        self,
        request: Request,
        secret_id: str,
    ):
        await self._authorize.require_perm(
            request=request, permission=PERM_CA_SECRETS_DELETE
        )
        await self._crud_secrets.resource_exists(_id=secret_id)

        authorities = await self._crud_authorities.find_referencing_ids(secret_id)
        spaces = await self._crud_spaces.find_referencing_ids(secret_id)
        if authorities or spaces:
            locations = [f"ca_authority:{a}" for a in authorities] + [
                f"ca_space:{s}" for s in spaces
            ]
            raise ResourceInUse(
                msg=(
                    f"secret '{secret_id}' is still referenced by: "
                    f"{', '.join(locations)}"
                )
            )

        await self._crud_secrets.delete(_id=secret_id)
        return {}

    async def search(
        self,
        request: Request,
        secret_id: str = Query(description="filter: regular_expressions", default=None),
        description: str = Query(
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
        await self._authorize.require_perm(request=request, permission=PERM_CA_GET)
        return await self._crud_secrets.search(
            _id=secret_id,
            description=description,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
