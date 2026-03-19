import logging
from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.controller.puppet_ca.v1.ca import ControllerPuppetCaV1CA
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService


class ControllerPuppetCaV1:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        ca_service: CAService,
    ):
        self._router = APIRouter()
        self._log = log

        self.router.include_router(
            ControllerPuppetCaV1CA(
                log=log,
                config=config,
                crud_authorities=crud_authorities,
                crud_spaces=crud_spaces,
                crud_certificates=crud_certificates,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
