# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import PlainTextResponse

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.pdb.query.v4 import ControllerPdbQueryV4
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_reports import CrudNodesReports


RETIRED_VERSIONS = ("v1", "v2", "v3")
ANY_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


class ControllerPdbQuery:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_reports: CrudNodesReports,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbQueryV4(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                crud_nodes_reports=crud_nodes_reports,
                authorize_client_cert=authorize_client_cert,
            ).router,
            prefix="/v4",
            responses={404: {"description": "Not found"}},
        )
        for version in RETIRED_VERSIONS:
            handler = self._retired(version)
            self.router.add_api_route(
                f"/{version}", handler, methods=ANY_METHODS, include_in_schema=False
            )
            self.router.add_api_route(
                f"/{version}/{{rest:path}}",
                handler,
                methods=ANY_METHODS,
                include_in_schema=False,
            )

    @staticmethod
    def _retired(version: str):
        async def handler(request: Request):
            return PlainTextResponse(
                f"The {version} API has been retired; please use v4", status_code=404
            )

        return handler

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def router(self):
        return self._router
