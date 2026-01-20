import logging

from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3.catalog import ControllerPuppetV3Catalog


class ControllerPuppetV3:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPuppetV3Catalog(
                log=log,
                config=config,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
