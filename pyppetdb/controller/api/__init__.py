import logging

import httpx
from fastapi import APIRouter

from pyppetdb.authorize import Authorize

from pyppetdb.controller.api.v1 import ControllerApiV1

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.hiera_key_models import CrudHieraKeyModels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers


class ControllerApi:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_ldap: CrudLdap,
        crud_hiera_key_models: CrudHieraKeyModels,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_teams: CrudTeams,
        crud_users: CrudUsers,
        crud_users_credentials: CrudCredentials,
        http: httpx.AsyncClient,
    ):
        self._router = APIRouter()
        self._log = log

        self.router.include_router(
            ControllerApiV1(
                log=log,
                authorize=authorize,
                crud_ldap=crud_ldap,
                crud_hiera_key_models=crud_hiera_key_models,
                crud_hiera_level_data=crud_hiera_level_data,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
                crud_teams=crud_teams,
                crud_users=crud_users,
                crud_users_credentials=crud_users_credentials,
                http=http,
            ).router,
            prefix="/v1",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router

    @property
    def log(self):
        return self._log
