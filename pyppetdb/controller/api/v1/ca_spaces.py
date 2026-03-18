import logging
from typing import Set
from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.ca_spaces import CASpacePut
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import filter_literal as ca_filter_literal
from pyppetdb.model.ca_authorities import filter_list as ca_filter_list
from pyppetdb.model.ca_spaces import filter_literal
from pyppetdb.model.ca_spaces import filter_list
from pyppetdb.model.ca_spaces import sort_literal
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import MetaMulti
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.errors import ResourceNotFound


class ControllerApiV1CASpaces:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_ca_spaces: CrudCASpaces,
        crud_ca_authorities: CrudCAAuthorities,
        crud_ca_certificates: CrudCACertificates,
        ca_service: CAService,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_ca_spaces = crud_ca_spaces
        self._crud_ca_authorities = crud_ca_authorities
        self._crud_ca_certificates = crud_ca_certificates
        self._ca_service = ca_service
        self._router = APIRouter(prefix="/ca/spaces", tags=["ca spaces"])

        self._router.add_api_route(
            "",
            self.search_spaces,
            methods=["GET"],
            response_model=CASpaceGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.create_space,
            methods=["POST"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.get_space,
            methods=["GET"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.update_space,
            methods=["PUT"],
            response_model=CASpaceGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}",
            self.delete_space,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{space_id}/ca",
            self.get_space_ca,
            methods=["GET"],
            response_model=CAAuthorityGetMulti,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

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

    async def get_space_ca(
        self,
        request: Request,
        space_id: str,
        fields: Set[ca_filter_literal] = Query(default=ca_filter_list),
        include_chain: bool = Query(default=True, description="include parent CAs"),
        include_crl: bool = Query(default=False, description="include CRL"),
    ) -> CAAuthorityGetMulti:
        await self.authorize.require_admin(request=request)

        try:
            space = await self.crud_ca_spaces.get(space_id, fields=list(fields))
            if not space.ca_id:
                raise ResourceNotFound(
                    details=f"Space '{space_id}' does not have a CA associated with it"
                )
            ca_ids = [space.ca_id] + space.ca_id_history

            cas = []
            processed_ca_ids = set()

            unique_ca_ids = []
            for cid in ca_ids:
                if cid not in unique_ca_ids:
                    unique_ca_ids.append(cid)

            crl_fields = ["crl"] if include_crl else []
            for ca_id in unique_ca_ids:
                try:
                    ca_ids_to_process = [ca_id]
                    while ca_ids_to_process:
                        cid = ca_ids_to_process.pop(0)
                        if cid in processed_ca_ids:
                            continue

                        ca = await self._crud_ca_authorities.get(cid, fields=crl_fields)
                        cas.append(ca)
                        processed_ca_ids.add(cid)

                        if include_chain and ca.parent_id:
                            ca_ids_to_process.append(ca.parent_id)
                except ResourceNotFound:
                    continue

            return CAAuthorityGetMulti(result=cas, meta=MetaMulti(result_size=len(cas)))
        except ResourceNotFound:
            raise ResourceNotFound(details=f"Space '{space_id}' not found")

    async def update_space(
        self,
        request: Request,
        space_id: str,
        data: CASpacePut,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        if data.ca_id:
            await self.crud_ca_authorities.get(data.ca_id)
        return await self.crud_ca_spaces.update(
            _id=space_id, payload=data, fields=list(fields)
        )

    async def create_space(
        self,
        request: Request,
        space_id: str,
        data: CASpacePost,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_ca_spaces.create(
            _id=space_id, payload=data, fields=list(fields)
        )

    async def get_space(
        self,
        request: Request,
        space_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_ca_spaces.get(_id=space_id, fields=list(fields))

    async def delete_space(
        self,
        request: Request,
        space_id: str,
    ):
        await self.authorize.require_admin(request=request)

        # Check if there are any certificates in this space
        count = await self.crud_ca_certificates.count({"space_id": space_id})
        if count > 0:
            raise QueryParamValidationError(
                msg=f"CA Space '{space_id}' still contains certificates"
            )

        await self.crud_ca_spaces.delete(_id=space_id)
        return {}

    async def search_spaces(
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
        await self.authorize.require_admin(request=request)
        return await self.crud_ca_spaces.search(
            _id=space_id,
            ca_id=ca_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
