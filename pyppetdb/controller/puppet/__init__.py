import logging

from fastapi import APIRouter
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3 import ControllerPuppetV3


class ControllerPuppet:
    def __init__(
        self,
        authorize_puppet: AuthorizePuppet,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPuppetV3(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            prefix="/v3",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
