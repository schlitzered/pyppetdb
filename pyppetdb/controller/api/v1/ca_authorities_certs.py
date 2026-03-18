import logging
from typing import Set
from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_certificates import CACertificateGetMulti
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_certificates import CACertificatePut
from pyppetdb.model.ca_certificates import filter_literal as cert_filter_literal
from pyppetdb.model.ca_certificates import filter_list as cert_filter_list
from pyppetdb.model.ca_certificates import sort_literal as cert_sort_literal
from pyppetdb.model.ca_certificates import CAStatus
from pyppetdb.model.common import sort_order_literal


class ControllerApiV1CAAuthoritiesCerts:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        ca_service: CAService,
    ):
        self._log = log
        self._authorize = authorize
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._ca_service = ca_service
        self._router = APIRouter(
            prefix="/ca/authorities/{ca_id}/certs}", tags=["ca authorities certs"]
        )

        self._router.add_api_route(
            "",
            self.get_authority_certs,
            methods=["GET"],
            response_model=CACertificateGetMulti,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{cert_id}",
            self.get_authority_certificate,
            methods=["GET"],
            response_model=CACertificateGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{cert_id}",
            self.update_authority_certificate_status,
            methods=["PUT"],
            response_model=CACertificateGet,
            response_model_exclude_unset=True,
        )
        self._router.add_api_route(
            "/{cert_id}",
            self.delete_authority_certificate,
            methods=["DELETE"],
            response_model=dict,
            response_model_exclude_unset=True,
        )

    @property
    def router(self):
        return self._router

    async def _populate_ca_info(self, cert: CACertificateGet) -> CACertificateGet:
        try:
            space = await self._crud_spaces.get(cert.space_id, fields=["ca_id"])
            ca = await self._crud_authorities.get(
                space.ca_id, fields=["certificate", "chain"]
            )
            cert.ca = ca.certificate
            cert.ca_chain = ca.chain
        except Exception as e:
            self._log.warning(
                f"Failed to populate CA info for cert {cert.id} in space {cert.space_id}: {e}"
            )
        return cert

    async def _find_cert_in_ca_spaces(
        self, ca_id: str, cert_id: str, fields: list
    ) -> CACertificateGet:
        spaces_multi = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        space_ids = [s["id"] for s in spaces_multi]

        multi = await self._crud_certificates.search_multi_spaces(
            space_ids=space_ids,
            _id=f"^{cert_id}$",  # exact match
            fields=fields,
            limit=1,
        )
        if not multi.result:
            raise ResourceNotFound(
                msg=f"Certificate '{cert_id}' not found for CA '{ca_id}'"
            )
        return multi.result[0]

    async def get_authority_certs(
        self,
        request: Request,
        ca_id: str,
        cert_id: str = Query(description="filter: regular_expressions", default=None),
        status: CAStatus = Query(default=None),
        fingerprint: str = Query(default=None),
        serial_number: str = Query(default=None),
        fields: Set[cert_filter_literal] = Query(default=cert_filter_list),
        sort: cert_sort_literal = Query(default="id"),
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

        # Find all spaces using this CA
        spaces_multi = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        space_ids = [s["id"] for s in spaces_multi]

        multi = await self._crud_certificates.search_multi_spaces(
            space_ids=space_ids,
            _id=cert_id,
            status=status,
            fingerprint=fingerprint,
            serial_number=serial_number,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

        if "ca" in fields or "ca_chain" in fields:
            for cert in multi.result:
                await self._populate_ca_info(cert)

        return multi

    async def get_authority_certificate(
        self,
        request: Request,
        ca_id: str,
        cert_id: str,
        fields: Set[cert_filter_literal] = Query(default=cert_filter_list),
    ):
        await self._authorize.require_admin(request=request)
        cert = await self._find_cert_in_ca_spaces(
            ca_id=ca_id, cert_id=cert_id, fields=list(fields)
        )
        if "ca" in fields or "ca_chain" in fields:
            await self._populate_ca_info(cert)
        return cert

    async def update_authority_certificate_status(
        self,
        request: Request,
        ca_id: str,
        cert_id: str,
        data: CACertificatePut,
        fields: Set[cert_filter_literal] = Query(default=cert_filter_list),
    ):
        await self._authorize.require_admin(request=request)
        # Find which space this cert belongs to
        temp_cert = await self._find_cert_in_ca_spaces(
            ca_id=ca_id, cert_id=cert_id, fields=["space_id"]
        )

        cert = await self._ca_service.update_certificate_status(
            temp_cert.space_id, cert_id, data
        )
        if "ca" in fields or "ca_chain" in fields:
            await self._populate_ca_info(cert)
        return cert

    async def delete_authority_certificate(
        self,
        request: Request,
        ca_id: str,
        cert_id: str,
    ):
        await self._authorize.require_admin(request=request)
        temp_cert = await self._find_cert_in_ca_spaces(
            ca_id=ca_id, cert_id=cert_id, fields=["space_id"]
        )
        await self._crud_certificates.delete(
            space_id=temp_cert.space_id, certname=cert_id
        )
        return {}
