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
from pyppetdb.controller.pdb.cmd import ControllerPdbCmd
from pyppetdb.controller.pdb.query import ControllerPdbQuery

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports


class ControllerPdb:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbCmd(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
                authorize_client_cert=authorize_client_cert,
            ).router,
            prefix="/cmd",
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPdbQuery(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                authorize_client_cert=authorize_client_cert,
            ).router,
            prefix="/query",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
