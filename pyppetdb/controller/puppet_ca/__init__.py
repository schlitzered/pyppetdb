import logging
from fastapi import APIRouter

from pyppetdb.controller.puppet_ca.v1 import ControllerPuppetCaV1
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.ca_crls import CrudCACRLs
from pyppetdb.ca.service import CAService

class ControllerPuppetCa:
    def __init__(
        self,
        log: logging.Logger,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        crud_crls: CrudCACRLs,
        ca_service: CAService,
    ):
        self._router = APIRouter()
        self._log = log

        self.router.include_router(
            ControllerPuppetCaV1(
                log=log,
                crud_authorities=crud_authorities,
                crud_spaces=crud_spaces,
                crud_certificates=crud_certificates,
                crud_crls=crud_crls,
                ca_service=ca_service,
            ).router,
            prefix="/v1",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
