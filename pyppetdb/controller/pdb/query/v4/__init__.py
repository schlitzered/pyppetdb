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

from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.controller.pdb.query.v4.resources import ControllerPdbQueryV4Resources


class ControllerPdbQueryV4:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbQueryV4Resources(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                authorize_client_cert=authorize_client_cert,
            ).router
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def router(self):

        return self._router
