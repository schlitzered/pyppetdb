import logging

from fastapi import APIRouter

from pyppetdb.config import Config

from pyppetdb.controller.puppet.v3 import ControllerPuppetV3


class ControllerPuppet:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPuppetV3(
                log=log,
                config=config,
            ).router,
            prefix="/v3",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
