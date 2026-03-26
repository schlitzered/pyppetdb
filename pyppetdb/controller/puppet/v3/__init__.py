import logging
import typing

from fastapi import APIRouter
import httpx

from pyppetdb.authorize import AuthorizeClientCert
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
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache


class ControllerPuppetV3:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes: typing.Optional[CrudNodes] = None,
        crud_nodes_catalog_cache: typing.Optional[CrudNodesCatalogCache] = None,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter()

        # Include specific endpoints first (they take precedence)
        self.router.include_router(
            ControllerPuppetV3Catalog(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
                crud_nodes=crud_nodes,
                crud_nodes_catalog_cache=crud_nodes_catalog_cache,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileBucketFile(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Facts(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Node(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileContent(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3FileMetadata(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPuppetV3Report(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def router(self):
        return self._router
