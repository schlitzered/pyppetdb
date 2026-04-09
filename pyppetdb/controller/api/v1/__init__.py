import logging

import httpx
from fastapi import APIRouter

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import AuthorizeClientCert

from pyppetdb.controller.api.v1.authenticate import ControllerApiV1Authenticate
from pyppetdb.controller.api.v1.hiera_key_models_static import (
    ControllerApiV1HieraKeyModelsStatic,
)
from pyppetdb.controller.api.v1.hiera_key_models_dynamic import (
    ControllerApiV1HieraKeyModelsDynamic,
)
from pyppetdb.controller.api.v1.hiera_keys import ControllerApiV1HieraKeys
from pyppetdb.controller.api.v1.hiera_levels import ControllerApiV1HieraLevels
from pyppetdb.controller.api.v1.hiera_level_data import ControllerApiV1HieraLevelData
from pyppetdb.controller.api.v1.hiera_lookup import ControllerApiV1HieraLookup
from pyppetdb.controller.api.v1.nodes import ControllerApiV1Nodes
from pyppetdb.controller.api.v1.nodes_catalogs import ControllerApiV1NodesCatalogs
from pyppetdb.controller.api.v1.nodes_groups import ControllerApiV1NodesGroups

from pyppetdb.controller.api.v1.nodes_reports import ControllerApiV1NodesReports
from pyppetdb.controller.api.v1.nodes_secrets_redactor import (
    ControllerApiV1NodesSecretsRedactor,
)
from pyppetdb.controller.api.v1.teams import ControllerApiV1Teams
from pyppetdb.controller.api.v1.users import ControllerApiV1Users
from pyppetdb.controller.api.v1.users_credentials import ControllerApiV1UsersCredentials
from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.ca_authorities_certs import (
    ControllerApiV1CAAuthoritiesCerts,
)
from pyppetdb.controller.api.v1.ca_spaces import ControllerApiV1CASpaces
from pyppetdb.controller.api.v1.ca_spaces_certs import (
    ControllerApiV1CASpacesCerts,
)
from pyppetdb.controller.api.v1.pyppetdb_nodes import ControllerApiV1PyppetDBNodes
from pyppetdb.controller.api.v1.ws import ControllerApiV1Ws


from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService


class ControllerApiV1:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        authorize_client_cert_puppet: AuthorizeClientCert,
        crud_ldap: CrudLdap,
        crud_hiera_key_models_static: CrudHieraKeyModelsStatic,
        crud_hiera_key_models_dynamic: CrudHieraKeyModelsDynamic,
        crud_hiera_keys: CrudHieraKeys,
        crud_hiera_levels: CrudHieraLevels,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_hiera_lookup_cache: CrudHieraLookupCache,
        crud_nodes: CrudNodes,
        crud_nodes_catalog_cache: CrudNodesCatalogCache,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_nodes_secrets_redactor: CrudNodesSecretsRedactor,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        crud_teams: CrudTeams,
        crud_users: CrudUsers,
        crud_users_credentials: CrudCredentials,
        crud_ca_authorities: CrudCAAuthorities,
        crud_ca_spaces: CrudCASpaces,
        crud_ca_certificates: CrudCACertificates,
        ca_service: CAService,
        http: httpx.AsyncClient,
        pyhiera,
    ):
        self._router = APIRouter()
        self._log = log

        self.router.include_router(
            ControllerApiV1Authenticate(
                log=log,
                authorize=authorize,
                crud_users=crud_users,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraKeyModelsStatic(
                log=log,
                authorize=authorize,
                crud_hiera_key_models_static=crud_hiera_key_models_static,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraKeyModelsDynamic(
                log=log,
                authorize=authorize,
                crud_hiera_key_models_dynamic=crud_hiera_key_models_dynamic,
                crud_hiera_keys=crud_hiera_keys,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraKeys(
                log=log,
                authorize=authorize,
                crud_hiera_key_models_static=crud_hiera_key_models_static,
                crud_hiera_key_models_dynamic=crud_hiera_key_models_dynamic,
                crud_hiera_keys=crud_hiera_keys,
                crud_hiera_level_data=crud_hiera_level_data,
                pyhiera=pyhiera,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraLevels(
                log=log,
                authorize=authorize,
                crud_hiera_levels=crud_hiera_levels,
                crud_hiera_level_data=crud_hiera_level_data,
                crud_hiera_lookup_cache=crud_hiera_lookup_cache,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraLevelData(
                log=log,
                authorize=authorize,
                crud_hiera_key_models_static=crud_hiera_key_models_static,
                crud_hiera_key_models_dynamic=crud_hiera_key_models_dynamic,
                crud_hiera_keys=crud_hiera_keys,
                crud_hiera_level_data=crud_hiera_level_data,
                crud_hiera_levels=crud_hiera_levels,
                crud_hiera_lookup_cache=crud_hiera_lookup_cache,
                pyhiera=pyhiera,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1HieraLookup(
                log=log,
                authorize=authorize,
                crud_hiera_lookup_cache=crud_hiera_lookup_cache,
                crud_hiera_keys=crud_hiera_keys,
                pyhiera=pyhiera,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1Nodes(
                log=log,
                authorize=authorize,
                crud_nodes=crud_nodes,
                crud_nodes_catalog_cache=crud_nodes_catalog_cache,
                crud_nodes_catalogs=crud_nodes_catalogs,
                crud_nodes_groups=crud_nodes_groups,
                crud_nodes_reports=crud_nodes_reports,
                crud_teams=crud_teams,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1NodesCatalogs(
                log=log,
                authorize=authorize,
                crud_nodes=crud_nodes,
                crud_nodes_catalogs=crud_nodes_catalogs,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1NodesGroups(
                log=log,
                authorize=authorize,
                crud_nodes=crud_nodes,
                crud_nodes_groups=crud_nodes_groups,
                crud_teams=crud_teams,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1NodesReports(
                log=log,
                authorize=authorize,
                crud_nodes=crud_nodes,
                crud_nodes_reports=crud_nodes_reports,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1NodesSecretsRedactor(
                log=log,
                authorize=authorize,
                crud_nodes_secrets_redactor=crud_nodes_secrets_redactor,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1Teams(
                log=log,
                authorize=authorize,
                crud_nodes_groups=crud_nodes_groups,
                crud_teams=crud_teams,
                crud_ldap=crud_ldap,
                crud_ca_spaces=crud_ca_spaces,
                crud_ca_authorities=crud_ca_authorities,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1Users(
                log=log,
                authorize=authorize,
                crud_teams=crud_teams,
                crud_users=crud_users,
                crud_users_credentials=crud_users_credentials,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1UsersCredentials(
                log=log,
                authorize=authorize,
                crud_users=crud_users,
                crud_users_credentials=crud_users_credentials,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1CAAuthorities(
                log=log,
                authorize=authorize,
                crud_authorities=crud_ca_authorities,
                crud_teams=crud_teams,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1CAAuthoritiesCerts(
                log=log,
                authorize=authorize,
                crud_authorities=crud_ca_authorities,
                crud_certificates=crud_ca_certificates,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1CASpaces(
                log=log,
                authorize=authorize,
                crud_ca_spaces=crud_ca_spaces,
                crud_ca_authorities=crud_ca_authorities,
                crud_ca_certificates=crud_ca_certificates,
                crud_teams=crud_teams,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1CASpacesCerts(
                log=log,
                authorize=authorize,
                crud_certificates=crud_ca_certificates,
                crud_authorities=crud_ca_authorities,
                crud_spaces=crud_ca_spaces,
                ca_service=ca_service,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1PyppetDBNodes(
                log=log,
                authorize=authorize,
                crud_pyppetdb_nodes=crud_pyppetdb_nodes,
            ).router,
            responses={404: {"description": "Not found"}},
        )

        self.router.include_router(
            ControllerApiV1Ws(
                log=log,
                authorize=authorize,
                authorize_client_cert=authorize_client_cert_puppet,
                crud_nodes=crud_nodes,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
