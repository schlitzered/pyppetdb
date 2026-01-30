import logging

import httpx
from fastapi import APIRouter

from pyppetdb.authorize import Authorize

from pyppetdb.config import Config

from pyppetdb.controller.api import ControllerApi
from pyppetdb.controller.oauth import ControllerOauth
from pyppetdb.controller.pdb import ControllerPdb
from pyppetdb.controller.puppet import ControllerPuppet

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.hiera_key_models import CrudHieraKeyModels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
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
        crud_hiera_key_models: CrudHieraKeyModels,
        crud_hiera_level_data: CrudHieraLevelData,
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
        self._router_dev = APIRouter()
        self._router_main = APIRouter()
        self._router_puppet = APIRouter()
        self._router_puppetdb = APIRouter()
        router_main = ControllerApi(
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
        ).router

        router_oauth = ControllerOauth(
            log=log,
            crud_oauth=crud_oauth,
            crud_users=crud_users,
            http=http,
        ).router

        router_pdb = ControllerPdb(
            log=log,
            config=config,
            crud_nodes=crud_nodes,
            crud_nodes_catalogs=crud_nodes_catalogs,
            crud_nodes_groups=crud_nodes_groups,
            crud_nodes_reports=crud_nodes_reports,
        ).router

        router_puppet = ControllerPuppet(
            log=log,
            config=config,
        )

        self.router_dev.include_router(
            router_main,
            prefix="/api",
            responses={404: {"description": "Not found"}},
        )
        self.router_main.include_router(
            router_main,
            prefix="/api",
            responses={404: {"description": "Not found"}},
        )

        self.router_dev.include_router(
            router_oauth,
            prefix="/oauth",
            responses={404: {"description": "Not found"}},
        )
        self.router_main.include_router(
            router_oauth,
            prefix="/oauth",
            responses={404: {"description": "Not found"}},
        )

        self.router_dev.include_router(
            router_pdb,
            prefix="/pdb",
            responses={404: {"description": "Not found"}},
        )
        self.router_puppetdb.include_router(
            router_pdb,
            prefix="/pdb",
            responses={404: {"description": "Not found"}},
        )

        self.router_dev.include_router(
            router_puppet.router,
            prefix="/puppet",
        )
        self.router_puppet.include_router(
            router_puppet.router,
            prefix="/puppet",
        )

    @property
    def router_dev(self):
        return self._router_dev

    @property
    def router_main(self):
        return self._router_main

    @property
    def router_puppet(self):
        return self._router_puppet

    @property
    def router_puppetdb(self):
        return self._router_puppetdb

    @property
    def log(self):
        return self._log
