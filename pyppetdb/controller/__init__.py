import logging

import httpx
from fastapi import APIRouter

from pyppetdb.authorize import Authorize

from pyppetdb.config import Config

from pyppetdb.controller.api import ControllerApi
from pyppetdb.controller.oauth import ControllerOauth
from pyppetdb.controller.pdb import ControllerPdb

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.oauth import CrudOAuth
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers


class Controller:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_ldap: CrudLdap,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_oauth: dict[str, CrudOAuth],
        crud_teams: CrudTeams,
        crud_users: CrudUsers,
        crud_users_credentials: CrudCredentials,
        http: httpx.AsyncClient,
        config: Config,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerApi(
                log=log,
                authorize=authorize,
                crud_ldap=crud_ldap,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
                crud_teams=crud_teams,
                crud_users=crud_users,
                crud_users_credentials=crud_users_credentials,
                http=http,
            ).router,
            prefix="/api",
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerOauth(
                log=log,
                crud_oauth=crud_oauth,
                crud_users=crud_users,
                http=http,
            ).router,
            prefix="/oauth",
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerPdb(
                log=log,
                config=config,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
            ).router,
            prefix="/pdb",
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router

    @property
    def log(self):
        return self._log
