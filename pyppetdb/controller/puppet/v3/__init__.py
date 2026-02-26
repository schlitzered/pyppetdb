import logging

from fastapi import APIRouter
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3.catalog import ControllerPuppetV3Catalog
from pyppetdb.controller.puppet.v3.facts import ControllerPuppetV3Facts
from pyppetdb.controller.puppet.v3.file_bucket_file import (
    ControllerPuppetV3FileBucketFile,
)
from pyppetdb.controller.puppet.v3.file_content import ControllerPuppetV3FileContent
from pyppetdb.controller.puppet.v3.file_metadata import ControllerPuppetV3FileMetadata
from pyppetdb.controller.puppet.v3.node import ControllerPuppetV3Node
from pyppetdb.controller.puppet.v3.report import ControllerPuppetV3Report


class ControllerPuppetV3:
    def __init__(
        self,
        authorize_puppet: AuthorizePuppet,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
    ):
        self._log = log
        self._router = APIRouter()

        # Include specific endpoints first (they take precedence)
        self.router.include_router(
            ControllerPuppetV3Catalog(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileBucketFile(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Facts(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Node(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileContent(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileMetadata(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Report(
                authorize_puppet=authorize_puppet,
                log=log,
                config=config,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
