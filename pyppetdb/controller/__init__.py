import logging

import httpx
from fastapi import APIRouter

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import AuthorizeClientCert

from pyppetdb.config import Config

from pyppetdb.controller.api import ControllerApi
from pyppetdb.controller.oauth import ControllerOauth
from pyppetdb.controller.pdb import ControllerPdb
from pyppetdb.controller.puppet import ControllerPuppet
from pyppetdb.controller.puppet_ca import ControllerPuppetCa

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.oauth import CrudOAuth
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService


class Controller:
    def __init__(
        self,
        log: logging.Logger,
        authorize_pyppetdb: AuthorizePyppetDB,
        authorize_client_cert_puppet: AuthorizeClientCert,
        authorize_client_cert_pdb: AuthorizeClientCert,
        crud_ldap: CrudLdap,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
        crud_hiera_key_models_dynamic: CrudHieraKeyModelsDynamic,
        crud_hiera_keys: CrudHieraKeys,
        crud_hiera_levels: CrudHieraLevels,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_hiera_lookup_cache: CrudHieraLookupCache,
        crud_job_definitions: CrudJobsDefinitions,
        crud_jobs: CrudJobs,
        crud_node_jobs: CrudJobsNodeJobs,
        crud_nodes: CrudNodes,
        crud_nodes_catalog_cache: CrudNodesCatalogCache,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_nodes_secrets_redactor: CrudNodesSecretsRedactor,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        crud_oauth: dict[str, CrudOAuth],
        crud_teams: CrudTeams,
        crud_users: CrudUsers,
        crud_users_credentials: CrudCredentials,
        crud_ca_authorities: CrudCAAuthorities,
        crud_ca_spaces: CrudCASpaces,
        crud_ca_certificates: CrudCACertificates,
        ca_service: CAService,
        http: httpx.AsyncClient,
        config: Config,
        redactor: NodesSecretsRedactor,
        pyhiera,
        ws_hub,
    ):
        self._log = log
        self._router_dev = APIRouter()
        self._router_main = APIRouter()
        self._router_puppet = APIRouter()
        self._router_puppetdb = APIRouter()
        router_main = ControllerApi(
            log=log,
            authorize=authorize_pyppetdb,
            authorize_client_cert_puppet=authorize_client_cert_puppet,
            crud_ldap=crud_ldap,
            crud_hiera_key_models_static=crud_hiera_key_models_static,
            crud_hiera_key_models_dynamic=crud_hiera_key_models_dynamic,
            crud_hiera_keys=crud_hiera_keys,
            crud_hiera_levels=crud_hiera_levels,
            crud_hiera_level_data=crud_hiera_level_data,
            crud_hiera_lookup_cache=crud_hiera_lookup_cache,
            crud_job_definitions=crud_job_definitions,
            crud_jobs=crud_jobs,
            crud_node_jobs=crud_node_jobs,
            crud_nodes=crud_nodes,
            crud_nodes_catalog_cache=crud_nodes_catalog_cache,
            crud_nodes_catalogs=crud_nodes_catalogs,
            crud_nodes_groups=crud_nodes_groups,
            crud_nodes_reports=crud_nodes_reports,
            crud_nodes_secrets_redactor=crud_nodes_secrets_redactor,
            crud_pyppetdb_nodes=crud_pyppetdb_nodes,
            crud_teams=crud_teams,
            crud_users=crud_users,
            crud_users_credentials=crud_users_credentials,
            crud_ca_authorities=crud_ca_authorities,
            crud_ca_spaces=crud_ca_spaces,
            crud_ca_certificates=crud_ca_certificates,
            ca_service=ca_service,
            http=http,
            config=config,
            redactor=redactor,
            pyhiera=pyhiera,
            ws_hub=ws_hub,
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
            authorize_client_cert=authorize_client_cert_pdb,
        ).router

        router_puppet = ControllerPuppet(
            log=log,
            config=config,
            http=http,
            crud_nodes=crud_nodes,
            crud_nodes_catalog_cache=crud_nodes_catalog_cache,
            authorize_client_cert=authorize_client_cert_puppet,
        ).router

        router_puppet_ca = ControllerPuppetCa(
            log=log,
            config=config,
            crud_authorities=crud_ca_authorities,
            crud_spaces=crud_ca_spaces,
            crud_certificates=crud_ca_certificates,
            crud_nodes=crud_nodes,
            ca_service=ca_service,
            authorize_client_cert=authorize_client_cert_puppet,
        ).router

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
            router_puppet,
        )
        self.router_puppet.include_router(
            router_puppet,
        )

        self.router_dev.include_router(
            router_puppet_ca,
            prefix="/puppet-ca",
        )
        self.router_puppet.include_router(
            router_puppet_ca,
            prefix="/puppet-ca",
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
