import logging
from typing import Set
from fastapi import APIRouter, Request, Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.model.ca_certificates import (
    CACertificateGet, CACertificateGetMulti, CACertificateStatusPut,
    filter_literal, filter_list, sort_literal, CAStatus
)
from pyppetdb.model.common import sort_order_literal

class ControllerApiV1CACertificates:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_certificates: CrudCACertificates,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_certificates = crud_certificates
        self._router = APIRouter(prefix="/ca/spaces/{space_id}/certs", tags=["ca"])

        self._router.add_api_route(
            "",
            self.search_certificates,
            methods=["GET"],
            response_model=CACertificateGetMulti,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{cert_id}",
            self.get_certificate,
            methods=["GET"],
            response_model=CACertificateGet,
            response_model_exclude_unset=True
        )
        self._router.add_api_route(
            "/{cert_id}",
            self.update_certificate_status,
            methods=["PUT"],
            response_model=CACertificateGet,
            response_model_exclude_unset=True
        )

    @property
    def router(self):
        return self._router

    async def search_certificates(
        self,
        request: Request,
        space_id: str,
        cert_id: str = Query(description="filter: regular_expressions", default=None),
        status: CAStatus = Query(default=None),
        fingerprint: str = Query(default=None),
        serial_number: str = Query(default=None),
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
        await self._authorize.require_admin(request=request)
        return await self._crud_certificates.search(
            _id=cert_id,
            space_id=space_id,
            status=status,
            fingerprint=fingerprint,
            serial_number=serial_number,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def get_certificate(
        self,
        request: Request,
        space_id: str,
        cert_id: str,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_certificates.get(space_id=space_id, certname=cert_id, fields=list(fields))

    async def update_certificate_status(
        self,
        request: Request,
        space_id: str,
        cert_id: str,
        data: CACertificateStatusPut,
        fields: Set[filter_literal] = Query(default=filter_list)
    ):
        await self._authorize.require_admin(request=request)
        if data.desired_state == "signed":
            return await self._crud_certificates.sign(space_id=space_id, certname=cert_id, fields=list(fields))
        elif data.desired_state == "revoked":
            return await self._crud_certificates.revoke(space_id=space_id, certname=cert_id, fields=list(fields))
