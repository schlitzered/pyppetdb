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
import typing

from fastapi import APIRouter
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3 import ControllerPuppetV3
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache


class ControllerPuppet:
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
        self._router = APIRouter()

        self.router.include_router(
            ControllerPuppetV3(
                log=log,
                config=config,
                http=http,
                authorize_client_cert=authorize_client_cert,
                crud_nodes=crud_nodes,
                crud_nodes_catalog_cache=crud_nodes_catalog_cache,
            ).router,
            prefix="/puppet/v3",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
