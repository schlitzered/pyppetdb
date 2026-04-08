import logging
from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.controller.puppet_ca.v1.ca import ControllerPuppetCaV1CA
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.ca.service import CAService


class ControllerPuppetCaV1:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        crud_nodes: CrudNodes,
        ca_service: CAService,
        authorize_client_cert: AuthorizeClientCert,
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
                crud_nodes=crud_nodes,
                ca_service=ca_service,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
