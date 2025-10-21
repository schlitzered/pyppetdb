import logging

from fastapi import APIRouter

from pyppetdb.config import Config

from pyppetdb.controller.pdb.query.v4.resources import ControllerPdbQueryV4Resources


class ControllerPdbQueryV4:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbQueryV4Resources(
                log=log,
                config=config,
            ).router
        )

    @property
    def router(self):
        return self._router
