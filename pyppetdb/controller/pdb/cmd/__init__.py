import logging

from fastapi import APIRouter

from pyppetdb.config import Config

from pyppetdb.controller.pdb.cmd.v1 import ControllerPdbCmdV1
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports


class ControllerPdbCmd:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerPdbCmdV1(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
            ).router
        )

    @property
    def router(self):
        return self._router
