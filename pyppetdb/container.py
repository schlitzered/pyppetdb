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

import socket
import logging
import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from pyppetdb.config import Config
from pyppetdb.crud.manager import CrudManager
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.nodes_reports import NodesReportsRedactor
from pyppetdb.crud.nodes_catalogs import NodesCatalogsRedactor
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService
from pyppetdb.jobs.service import JobService
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.ws.hub import WsHub
from pyppetdb.hiera import PyHiera
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraKeyModelsDynamic
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import DuplicateResource
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_spaces import CASpacePost


class AppContainer:
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        mongo_db: AsyncIOMotorDatabase,
        http: httpx.AsyncClient = None,
        ldap_pool=None,
        crud_oauth=None,
    ):
        self.config = config
        self.log = log
        self.http = http
        self.ldap_pool = ldap_pool
        self.mongo_db = mongo_db
        self.crud_oauth = crud_oauth or {}

        self.crud_manager = CrudManager(
            log=log,
        )

        self.nodes_data_protector = NodesDataProtector(
            app_secret_key=config.app.secretkey,
            log=log,
        )

        self.nodes_secrets_redactor = NodesSecretsRedactor(
            protector=self.nodes_data_protector,
            log=log,
        )

        self.nodes_reports_redactor = NodesReportsRedactor(
            redactor=self.nodes_secrets_redactor,
            log=log,
        )

        self.nodes_catalogs_redactor = NodesCatalogsRedactor(
            redactor=self.nodes_secrets_redactor,
            log=log,
        )

        self.crud_ldap = CrudLdap(
            log=log,
            ldap_base_dn=config.ldap.basedn,
            ldap_bind_dn=config.ldap.binddn,
            ldap_pool=ldap_pool,
            ldap_url=config.ldap.url,
            ldap_user_pattern=config.ldap.userpattern,
        )

        self.crud_hiera_levels = self.crud_manager.register(
            crud=CrudHieraLevels(
                config=config,
                log=log,
                coll=mongo_db["hiera_levels"],
            )
        )

        self.crud_hiera_level_data = self.crud_manager.register(
            crud=CrudHieraLevelData(
                config=config,
                log=log,
                coll=mongo_db["hiera_level_data"],
            )
        )

        self.crud_hiera_lookup_cache = self.crud_manager.register(
            crud=CrudHieraLookupCache(
                config=config,
                log=log,
                coll=mongo_db["hiera_lookup_cache"],
            )
        )

        self.crud_job_definitions = self.crud_manager.register(
            crud=CrudJobsDefinitions(
                config=config,
                log=log,
                coll=mongo_db["jobs_definitions"],
            )
        )

        self.crud_node_jobs = self.crud_manager.register(
            crud=CrudJobsNodeJobs(
                config=config,
                log=log,
                coll=mongo_db["jobs_node_jobs"],
            )
        )

        self.crud_jobs = self.crud_manager.register(
            crud=CrudJobs(
                config=config,
                log=log,
                coll=mongo_db["jobs"],
            )
        )

        self.crud_nodes_catalog_cache = self.crud_manager.register(
            crud=CrudNodesCatalogCache(
                config=config,
                log=log,
                coll=mongo_db["nodes_catalog_cache"],
                protector=self.nodes_data_protector,
            )
        )

        self.crud_nodes = self.crud_manager.register(
            crud=CrudNodes(
                config=config,
                log=log,
                coll=mongo_db["nodes"],
            )
        )

        self.crud_nodes_secrets_redactor = self.crud_manager.register(
            crud=CrudNodesSecretsRedactor(
                config=config,
                log=log,
                coll=mongo_db["nodes_secrets_redactor"],
                redactor=self.nodes_secrets_redactor,
            )
        )

        self.crud_nodes_catalogs = self.crud_manager.register(
            crud=CrudNodesCatalogs(
                config=config,
                log=log,
                coll=mongo_db["nodes_catalogs"],
                secret_manager=self.nodes_catalogs_redactor,
            )
        )

        self.crud_nodes_groups = self.crud_manager.register(
            crud=CrudNodesGroups(
                config=config,
                log=log,
                coll=mongo_db["nodes_groups"],
            )
        )

        self.crud_nodes_reports = self.crud_manager.register(
            crud=CrudNodesReports(
                config=config,
                log=log,
                coll=mongo_db["nodes_reports"],
                secret_manager=self.nodes_reports_redactor,
            )
        )

        self.crud_pyppetdb_nodes = self.crud_manager.register(
            crud=CrudPyppetDBNodes(
                config=config,
                log=log,
                coll=mongo_db["pyppetdb_nodes"],
            )
        )

        self.crud_teams = self.crud_manager.register(
            crud=CrudTeams(
                config=config,
                log=log,
                coll=mongo_db["teams"],
            )
        )

        self.crud_users = self.crud_manager.register(
            crud=CrudUsers(
                config=config,
                log=log,
                coll=mongo_db["users"],
                crud_ldap=self.crud_ldap,
            )
        )

        self.crud_users_credentials = self.crud_manager.register(
            crud=CrudCredentials(
                config=config,
                log=log,
                coll=mongo_db["users_credentials"],
            )
        )

        self.crud_ca_authorities = self.crud_manager.register(
            crud=CrudCAAuthorities(
                config=config,
                log=log,
                coll=mongo_db["ca_authorities"],
                protector=self.nodes_data_protector,
            )
        )

        self.crud_ca_spaces = self.crud_manager.register(
            crud=CrudCASpaces(
                config=config,
                log=log,
                coll=mongo_db["ca_spaces"],
                protector=self.nodes_data_protector,
            )
        )

        self.crud_ca_certificates = self.crud_manager.register(
            crud=CrudCACertificates(
                config=config,
                log=log,
                coll=mongo_db["ca_certificates"],
            )
        )

        self.ca_service = CAService(
            log=log,
            config=config,
            crud_authorities=self.crud_ca_authorities,
            crud_spaces=self.crud_ca_spaces,
            crud_certificates=self.crud_ca_certificates,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
        )

        self.authorize_client_cert_puppet = AuthorizeClientCert(
            log=log,
            config=config,
            trusted_cns=config.app.puppet.trustedCns,
            crud_ca_certificates=self.crud_ca_certificates,
        )

        self.ws_hub = WsHub(
            log=log,
            config=config,
            crud_nodes=self.crud_nodes,
            crud_jobs=self.crud_jobs,
            crud_job_definitions=self.crud_job_definitions,
            crud_node_jobs=self.crud_node_jobs,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
            redactor=self.nodes_secrets_redactor,
            authorize_client_cert=self.authorize_client_cert_puppet,
        )

        self.job_service = JobService(
            log=log,
            config=config,
            crud_node_jobs=self.crud_node_jobs,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
            hub=self.ws_hub,
        )

        self.pyhiera = PyHiera(
            log=log,
            crud_hiera_level_data=self.crud_hiera_level_data,
            hiera_level_ids=self.crud_hiera_levels.cache.level_ids,
            hiera_config=config.app.main.hiera,
        )

        self.crud_hiera_key_models_dynamic = self.crud_manager.register(
            crud=CrudHieraKeyModelsDynamic(
                config=config,
                log=log,
                coll=mongo_db["hiera_key_models_dynamic"],
                pyhiera=self.pyhiera,
            )
        )

        self.crud_hiera_keys = self.crud_manager.register(
            crud=CrudHieraKeys(
                config=config,
                log=log,
                coll=mongo_db["hiera_keys"],
                pyhiera=self.pyhiera,
            )
        )

        self.crud_hiera_key_models_static = CrudHieraKeyModelsStatic(
            config=config,
            log=log,
            pyhiera=self.pyhiera,
        )

        self.authorize_pyppetdb = AuthorizePyppetDB(
            log=log,
            crud_node_groups=self.crud_nodes_groups,
            crud_teams=self.crud_teams,
            crud_users=self.crud_users,
            crud_users_credentials=self.crud_users_credentials,
        )

        self.authorize_client_cert_pdb = AuthorizeClientCert(
            log=log,
            config=config,
            trusted_cns=config.app.puppetdb.trustedCns,
            crud_ca_certificates=self.crud_ca_certificates,
        )

    async def init(self):
        await self.crud_manager.init_all()
        await self._ensure_default_ca_setup()

    async def _ensure_default_ca_setup(self):
        default_id = "puppet-ca"
        try:
            await self.ca_service._crud_authorities.get(
                _id=default_id,
                fields=["id"],
            )
            self.log.info(msg=f"Default CA Authority '{default_id}' already exists")
        except ResourceNotFound:
            self.log.info(msg=f"Creating default CA Authority '{default_id}'")
            try:
                await self.ca_service.create_authority(
                    _id=default_id,
                    payload=CAAuthorityPost(
                        cn="PyppetDB Internal Root CA",
                        organization="PyppetDB",
                        country="DE",
                        state="Hessen",
                        validity_days=3650,
                    ),
                    fields=[],
                )
            except DuplicateResource:
                self.log.info(
                    msg=f"Default CA Authority '{default_id}' was created by another process"
                )

        try:
            await self.ca_service._crud_spaces.get(
                _id=default_id,
                fields=["id"],
            )
            self.log.info(msg=f"Default CA Space '{default_id}' already exists")
        except ResourceNotFound:
            self.log.info(msg=f"Creating default CA Space '{default_id}'")
            try:
                await self.ca_service.create_space(
                    _id=default_id,
                    payload=CASpacePost(
                        ca_id=default_id,
                    ),
                    fields=[],
                )
            except DuplicateResource:
                self.log.info(
                    msg=f"Default CA Space '{default_id}' was created by another process"
                )

    async def close(self):
        instance_id = f"{socket.getfqdn()}:{self.config.app.main.port}"
        self.log.info(msg=f"Removing PyppetDB node '{instance_id}' from database...")
        try:
            await self.crud_pyppetdb_nodes.delete(
                _id=instance_id,
            )
        except Exception:
            pass

        await self.crud_nodes.cleanup_remote_agents(
            via=instance_id,
        )

        if self.ldap_pool:
            self.log.info(msg="Closing LDAP pool...")
            await self.ldap_pool.close()

        if self.http:
            self.log.info(msg="Closing HTTP client...")
            await self.http.aclose()

        if self.mongo_db is not None:
            self.log.info(msg="Closing MongoDB client...")
            self.mongo_db.client.close()
