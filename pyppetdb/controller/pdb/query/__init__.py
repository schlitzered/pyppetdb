import logging

from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.controller.pdb.query.v4 import ControllerPdbQueryV4


class ControllerPdbQuery:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbQueryV4(
                log=log,
                config=config,
                authorize_client_cert=authorize_client_cert,
            ).router,
            prefix="/v4",
            responses={404: {"description": "Not found"}},
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def router(self):
        return self._router
