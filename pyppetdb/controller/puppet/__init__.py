import logging
import typing

from fastapi import APIRouter
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v1.ca import ControllerPuppetV1CA
from pyppetdb.controller.puppet.v3 import ControllerPuppetV3
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache


class ControllerPuppet:
    def __init__(
        self,
        authorize_puppet: AuthorizePuppet,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
        crud_nodes_catalog_cache: typing.Optional[CrudNodesCatalogCache] = None,
        crud_ca_authorities: typing.Optional[CrudCAAuthorities] = None,
        crud_ca_spaces: typing.Optional[CrudCASpaces] = None,
        crud_ca_certificates: typing.Optional[CrudCACertificates] = None,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPuppetV3(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
                crud_nodes_catalog_cache=crud_nodes_catalog_cache,
            ).router,
            prefix="/v3",
            responses={404: {"description": "Not found"}},
        )

        if (
            crud_ca_authorities is not None
            and crud_ca_spaces is not None
            and crud_ca_certificates is not None
        ):
            self.router.include_router(
                ControllerPuppetV1CA(
                    log=log,
                    crud_authorities=crud_ca_authorities,
                    crud_spaces=crud_ca_spaces,
                    crud_certificates=crud_ca_certificates,
                ).router
            )

    @property
    def router(self):
        return self._router
