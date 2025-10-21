import logging

from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.controller.pdb.query.v4 import ControllerPdbQueryV4


class ControllerPdbQuery:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbQueryV4(
                log=log,
                config=config,
            ).router,
            prefix="/v4",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
