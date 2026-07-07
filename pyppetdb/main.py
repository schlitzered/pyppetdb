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

import warnings

try:
    from authlib.deprecate import AuthlibDeprecationWarning

    # TODO: Remove this warning suppression once Authlib is updated to a version
    # that fixes internal deprecated imports (Issue #880).
    # Suppress Authlib deprecation warning regarding jose/joserfc transition
    warnings.filterwarnings("ignore", category=AuthlibDeprecationWarning)
except ImportError:
    pass

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import secrets
import signal
import socket
import ssl
import string
import sys
import time
from pathlib import Path
import datetime

from authlib.integrations.starlette_client import OAuth
import bonsai.asyncio
import httpx
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorDatabase
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import structlog
from structlog.stdlib import ProcessorFormatter

import pyppetdb.controller
import pyppetdb.controller.oauth
import pyppetdb.ca.utils
from pyppetdb.ca.protocol import ClientCertProtocol, ClientCertWebSocketsProtocol

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import AuthorizeClientCert

from pyppetdb.config import Config
from pyppetdb.config import ConfigLdap as SettingsLdap
from pyppetdb.config import ConfigOAuth as SettingsOAuth

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
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.crud.oauth import CrudOAuthGitHub
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.manager import CrudManager
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService
from pyppetdb.ca.utils import CAUtils

from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.users import UserPost

from pyppetdb.hiera import PyHiera
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.ws.hub import WsHub
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.nodes_reports import NodesReportsRedactor
from pyppetdb.crud.nodes_catalogs import NodesCatalogsRedactor

from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import ResourceNotFound

version = "0.0.0"


settings = Config()


async def expire_scheduled_jobs_worker(
    log: logging.Logger,
    config: Config,
    crud_node_jobs: CrudJobsNodeJobs,
    crud_pyppetdb_nodes: CrudPyppetDBNodes,
    hub: WsHub,
):
    log.info("starting scheduled jobs expiration worker")
    instance_id = f"{socket.getfqdn()}:{config.app.main.port}"
    while True:
        try:
            leader = await crud_pyppetdb_nodes.get_leader()
            if leader == instance_id:
                expired_jobs = await crud_node_jobs.expire_scheduled_jobs(
                    timeout_seconds=config.jobs.expireSeconds
                )
                for job in expired_jobs:
                    log.warning(
                        f"Job {job.job_id} for node {job.node_id} expired and marked as failed"
                    )
                    await hub.job_finished(
                        node_id=job.node_id,
                        job_id=job.job_id,
                        status="failed",
                        exit_code=1,
                    )
            else:
                log.debug(
                    f"Skipping job expiration, I am not the leader (Leader: {leader}, Me: {instance_id})"
                )
        except Exception as e:
            log.error(f"Error in scheduled jobs expiration worker: {e}")

        await asyncio.sleep(60)


async def migrate_ca_configs(
    log: logging.Logger,
    ca_service: CAService,
):
    from pyppetdb.model.ca_validation import CAValidationConfig

    default_config = CAValidationConfig().model_dump()

    # Authorities
    authorities_coll = ca_service._crud_authorities.coll
    res_auth = await authorities_coll.update_many(
        {"validation_config": {"$exists": False}},
        {"$set": {"validation_config": default_config}},
    )
    if res_auth.modified_count > 0:
        log.info(
            f"Migrated {res_auth.modified_count} CA Authorities with default validation config"
        )

    # Spaces
    spaces_coll = ca_service._crud_spaces.coll
    res_spaces = await spaces_coll.update_many(
        {"validation_config": {"$exists": False}},
        {"$set": {"validation_config": default_config}},
    )
    if res_spaces.modified_count > 0:
        log.info(
            f"Migrated {res_spaces.modified_count} CA Spaces with default validation config"
        )


async def ensure_default_ca_setup(
    log: logging.Logger,
    ca_service: CAService,
):
    default_id = "puppet-ca"

    try:
        await ca_service._crud_authorities.get(default_id, fields=["id"])
        log.info(f"Default CA Authority '{default_id}' already exists")
    except ResourceNotFound:
        log.info(f"Creating default CA Authority '{default_id}'")
        try:
            await ca_service.create_authority(
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
            log.info(
                f"Default CA Authority '{default_id}' was created by another process"
            )

    try:
        await ca_service._crud_spaces.get(default_id, fields=["id"])
        log.info(f"Default CA Space '{default_id}' already exists")
    except ResourceNotFound:
        log.info(f"Creating default CA Space '{default_id}'")
        try:
            await ca_service.create_space(
                _id=default_id,
                payload=CASpacePost(ca_id=default_id),
                fields=[],
            )
        except DuplicateResource:
            log.info(f"Default CA Space '{default_id}' was created by another process")


async def prepare_env():
    env = dict()
    log = setup_logging(
        settings.app.loglevel,
        settings.app.logstruct,
    )
    env["log"] = log

    log.info(settings)

    http = httpx.AsyncClient(timeout=60)
    env["http"] = http

    ldap_pool = await setup_ldap(
        log=log,
        settings_ldap=settings.ldap,
    )
    env["ldap_pool"] = ldap_pool

    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )
    env["mongo_db"] = mongo_db

    crud_manager = CrudManager(log=log)

    nodes_data_protector = NodesDataProtector(
        app_secret_key=settings.app.secretkey,
        log=log,
    )
    env["nodes_data_protector"] = nodes_data_protector

    nodes_secrets_redactor = NodesSecretsRedactor(
        protector=nodes_data_protector,
        log=log,
    )
    env["nodes_secrets_redactor"] = nodes_secrets_redactor

    nodes_reports_redactor = NodesReportsRedactor(
        redactor=nodes_secrets_redactor,
        log=log,
    )
    env["nodes_reports_redactor"] = nodes_reports_redactor

    nodes_catalogs_redactor = NodesCatalogsRedactor(
        redactor=nodes_secrets_redactor,
        log=log,
    )
    env["nodes_catalogs_redactor"] = nodes_catalogs_redactor

    crud_oauth = setup_oauth_providers(
        log=log,
        http=http,
        oauth_settings=settings.oauth,
    )
    env["crud_oauth"] = crud_oauth

    crud_ldap = CrudLdap(
        log=log,
        ldap_base_dn=settings.ldap.basedn,
        ldap_bind_dn=settings.ldap.binddn,
        ldap_pool=ldap_pool,
        ldap_url=settings.ldap.url,
        ldap_user_pattern=settings.ldap.userpattern,
    )
    env["crud_ldap"] = crud_ldap

    crud_hiera_levels = crud_manager.register(
        CrudHieraLevels(
            config=settings,
            log=log,
            coll=mongo_db["hiera_levels"],
        )
    )
    env["crud_hiera_levels"] = crud_hiera_levels

    crud_hiera_level_data = crud_manager.register(
        CrudHieraLevelData(
            config=settings,
            log=log,
            coll=mongo_db["hiera_level_data"],
        )
    )
    env["crud_hiera_level_data"] = crud_hiera_level_data

    crud_hiera_lookup_cache = crud_manager.register(
        CrudHieraLookupCache(
            config=settings,
            log=log,
            coll=mongo_db["hiera_lookup_cache"],
        )
    )
    env["crud_hiera_lookup_cache"] = crud_hiera_lookup_cache

    crud_job_definitions = crud_manager.register(
        CrudJobsDefinitions(
            config=settings,
            log=log,
            coll=mongo_db["jobs_definitions"],
        )
    )
    env["crud_job_definitions"] = crud_job_definitions

    crud_node_jobs = crud_manager.register(
        CrudJobsNodeJobs(
            config=settings,
            log=log,
            coll=mongo_db["jobs_node_jobs"],
        )
    )
    env["crud_node_jobs"] = crud_node_jobs

    crud_jobs = crud_manager.register(
        CrudJobs(
            config=settings,
            log=log,
            coll=mongo_db["jobs"],
        )
    )
    env["crud_jobs"] = crud_jobs

    crud_nodes_catalog_cache = crud_manager.register(
        CrudNodesCatalogCache(
            config=settings,
            log=log,
            coll=mongo_db["nodes_catalog_cache"],
            protector=nodes_data_protector,
        )
    )
    env["crud_nodes_catalog_cache"] = crud_nodes_catalog_cache

    crud_nodes = crud_manager.register(
        CrudNodes(
            config=settings,
            log=log,
            coll=mongo_db["nodes"],
        )
    )
    env["crud_nodes"] = crud_nodes

    crud_nodes_secrets_redactor = crud_manager.register(
        CrudNodesSecretsRedactor(
            config=settings,
            log=log,
            coll=mongo_db["nodes_secrets_redactor"],
            redactor=nodes_secrets_redactor,
        )
    )
    env["crud_nodes_secrets_redactor"] = crud_nodes_secrets_redactor

    crud_nodes_catalogs = crud_manager.register(
        CrudNodesCatalogs(
            config=settings,
            log=log,
            coll=mongo_db["nodes_catalogs"],
            secret_manager=nodes_catalogs_redactor,
        )
    )
    env["crud_nodes_catalogs"] = crud_nodes_catalogs

    crud_nodes_groups = crud_manager.register(
        CrudNodesGroups(
            config=settings,
            log=log,
            coll=mongo_db["nodes_groups"],
        )
    )
    env["crud_nodes_groups"] = crud_nodes_groups

    crud_nodes_reports = crud_manager.register(
        CrudNodesReports(
            config=settings,
            log=log,
            coll=mongo_db["nodes_reports"],
            secret_manager=nodes_reports_redactor,
        )
    )
    env["crud_nodes_reports"] = crud_nodes_reports

    crud_pyppetdb_nodes = crud_manager.register(
        CrudPyppetDBNodes(
            config=settings,
            log=log,
            coll=mongo_db["pyppetdb_nodes"],
        )
    )
    env["crud_pyppetdb_nodes"] = crud_pyppetdb_nodes

    crud_teams = crud_manager.register(
        CrudTeams(
            config=settings,
            log=log,
            coll=mongo_db["teams"],
        )
    )
    env["crud_teams"] = crud_teams

    crud_users = crud_manager.register(
        CrudUsers(
            config=settings,
            log=log,
            coll=mongo_db["users"],
            crud_ldap=crud_ldap,
        )
    )
    env["crud_users"] = crud_users

    crud_users_credentials = crud_manager.register(
        CrudCredentials(
            config=settings,
            log=log,
            coll=mongo_db["users_credentials"],
        )
    )
    env["crud_users_credentials"] = crud_users_credentials

    crud_ca_authorities = crud_manager.register(
        CrudCAAuthorities(
            config=settings,
            log=log,
            coll=mongo_db["ca_authorities"],
            protector=nodes_data_protector,
        )
    )
    env["crud_ca_authorities"] = crud_ca_authorities

    crud_ca_spaces = crud_manager.register(
        CrudCASpaces(
            config=settings,
            log=log,
            coll=mongo_db["ca_spaces"],
            protector=nodes_data_protector,
        )
    )
    env["crud_ca_spaces"] = crud_ca_spaces

    crud_ca_certificates = crud_manager.register(
        CrudCACertificates(
            config=settings,
            log=log,
            coll=mongo_db["ca_certificates"],
        )
    )
    env["crud_ca_certificates"] = crud_ca_certificates

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
        crud_pyppetdb_nodes=crud_pyppetdb_nodes,
    )
    env["ca_service"] = ca_service

    authorize_client_cert_puppet = AuthorizeClientCert(
        log=log,
        config=settings,
        trusted_cns=settings.app.puppet.trustedCns,
        crud_ca_certificates=crud_ca_certificates,
    )
    env["authorize_client_cert_puppet"] = authorize_client_cert_puppet

    ws_hub = WsHub(
        log=log,
        config=settings,
        crud_nodes=crud_nodes,
        crud_jobs=crud_jobs,
        crud_job_definitions=crud_job_definitions,
        crud_node_jobs=crud_node_jobs,
        crud_pyppetdb_nodes=crud_pyppetdb_nodes,
        redactor=nodes_secrets_redactor,
        authorize_client_cert=authorize_client_cert_puppet,
    )
    env["ws_hub"] = ws_hub

    pyhiera = PyHiera(
        log=log,
        crud_hiera_level_data=crud_hiera_level_data,
        hiera_level_ids=crud_hiera_levels.cache.level_ids,
        hiera_config=settings.app.main.hiera,
    )
    env["pyhiera"] = pyhiera

    crud_hiera_key_models_dynamic = crud_manager.register(
        CrudHieraKeyModelsDynamic(
            config=settings,
            log=log,
            coll=mongo_db["hiera_key_models_dynamic"],
            pyhiera=pyhiera,
        )
    )
    env["crud_hiera_key_models_dynamic"] = crud_hiera_key_models_dynamic

    crud_hiera_keys = crud_manager.register(
        CrudHieraKeys(
            config=settings,
            log=log,
            coll=mongo_db["hiera_keys"],
            pyhiera=pyhiera,
        )
    )
    env["crud_hiera_keys"] = crud_hiera_keys

    crud_hiera_key_models_static = CrudHieraKeyModelsStatic(
        config=settings,
        log=log,
        pyhiera=pyhiera,
    )
    env["crud_hiera_key_models_static"] = crud_hiera_key_models_static

    await crud_manager.init_all()

    authorize_pyppetdb = AuthorizePyppetDB(
        log=log,
        crud_node_groups=crud_nodes_groups,
        crud_teams=crud_teams,
        crud_users=crud_users,
        crud_users_credentials=crud_users_credentials,
    )
    env["authorize_pyppetdb"] = authorize_pyppetdb

    authorize_client_cert_pdb = AuthorizeClientCert(
        log=log,
        config=settings,
        trusted_cns=settings.app.puppetdb.trustedCns,
        crud_ca_certificates=crud_ca_certificates,
    )
    env["authorize_client_cert_pdb"] = authorize_client_cert_pdb

    await ensure_default_ca_setup(
        log=log,
        ca_service=ca_service,
    )

    return env


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = await prepare_env()

    controller = pyppetdb.controller.Controller(
        log=env["log"],
        authorize_pyppetdb=env["authorize_pyppetdb"],
        authorize_client_cert_puppet=env["authorize_client_cert_puppet"],
        authorize_client_cert_pdb=env["authorize_client_cert_pdb"],
        crud_ldap=env["crud_ldap"],
        crud_hiera_key_models_static=env["crud_hiera_key_models_static"],
        crud_hiera_key_models_dynamic=env["crud_hiera_key_models_dynamic"],
        crud_hiera_keys=env["crud_hiera_keys"],
        crud_hiera_levels=env["crud_hiera_levels"],
        crud_hiera_level_data=env["crud_hiera_level_data"],
        crud_hiera_lookup_cache=env["crud_hiera_lookup_cache"],
        crud_job_definitions=env["crud_job_definitions"],
        crud_jobs=env["crud_jobs"],
        crud_node_jobs=env["crud_node_jobs"],
        crud_nodes=env["crud_nodes"],
        crud_nodes_catalog_cache=env["crud_nodes_catalog_cache"],
        crud_nodes_catalogs=env["crud_nodes_catalogs"],
        crud_nodes_groups=env["crud_nodes_groups"],
        crud_nodes_reports=env["crud_nodes_reports"],
        crud_nodes_secrets_redactor=env["crud_nodes_secrets_redactor"],
        crud_pyppetdb_nodes=env["crud_pyppetdb_nodes"],
        crud_teams=env["crud_teams"],
        crud_users=env["crud_users"],
        crud_users_credentials=env["crud_users_credentials"],
        crud_ca_authorities=env["crud_ca_authorities"],
        crud_ca_spaces=env["crud_ca_spaces"],
        crud_ca_certificates=env["crud_ca_certificates"],
        ca_service=env["ca_service"],
        crud_oauth=env["crud_oauth"],
        http=env["http"],
        config=settings,
        pyhiera=env["pyhiera"],
        redactor=env["nodes_secrets_redactor"],
        ws_hub=env["ws_hub"],
    )

    if settings.app.main.enable:
        app.include_router(router=controller.router_main)
    if settings.app.puppetdb.enable:
        app.include_router(router=controller.router_puppetdb)
    if settings.app.puppet.enable:
        app.include_router(router=controller.router_puppet)

    refresh_task = None
    heartbeat_task = asyncio.create_task(
        coro=pyppetdb_nodes_heartbeat_worker(
            crud=env["crud_pyppetdb_nodes"],
            port=settings.app.main.port,
        ),
        name="pyppetdb-nodes-heartbeat",
    )
    expire_jobs_task = asyncio.create_task(
        coro=expire_scheduled_jobs_worker(
            log=env["log"],
            config=settings,
            crud_node_jobs=env["crud_node_jobs"],
            crud_pyppetdb_nodes=env["crud_pyppetdb_nodes"],
            hub=env["ws_hub"],
        ),
        name="expire-scheduled-jobs",
    )
    ws_hub_task = asyncio.create_task(
        coro=env["ws_hub"].run(),
        name="ws-hub-background",
    )
    if settings.ca.enableCrlRefresh:
        refresh_task = asyncio.create_task(
            coro=env["ca_service"].crl_refresh_worker(),
            name="ca-crl-refresh",
        )

    yield

    if heartbeat_task:
        heartbeat_task.cancel()
    if expire_jobs_task:
        expire_jobs_task.cancel()
    if ws_hub_task:
        env["ws_hub"].stop()
        ws_hub_task.cancel()
    if refresh_task:
        refresh_task.cancel()

    instance_id = f"{socket.getfqdn()}:{settings.app.main.port}"
    log = env["log"]
    log.info(f"Removing PyppetDB node '{instance_id}' from database...")
    with suppress(Exception):
        await env["crud_pyppetdb_nodes"].delete(_id=instance_id)

    await env["crud_nodes"].cleanup_remote_agents(via=instance_id)

    if "ldap_pool" in env and env["ldap_pool"]:
        log.info("Closing LDAP pool...")
        await env["ldap_pool"].close()

    if "http" in env and env["http"]:
        log.info("Closing HTTP client...")
        await env["http"].aclose()

    if "mongo_db" in env and env["mongo_db"] is not None:
        log.info(msg="Closing MongoDB client...")
        env["mongo_db"].client.close()


lifespan_dev = lifespan


async def setup_ldap(log: logging.Logger, settings_ldap: SettingsLdap):
    if not settings_ldap.url:
        log.info("ldap not configured")
        return
    log.info(f"setting up ldap with {settings_ldap.url} as a backend")
    if not settings_ldap.binddn:
        log.fatal("ldap binddn not configured")
        sys.exit(1)
    if not settings_ldap.password:
        log.fatal("ldap password not configured")
        sys.exit(1)
    client = bonsai.LDAPClient(settings_ldap.url)
    client.set_credentials("SIMPLE", settings_ldap.binddn, settings_ldap.password)
    pool = bonsai.asyncio.AIOConnectionPool(client=client, maxconn=30)
    await pool.open()
    return pool


def setup_logging(log_level, logstruct: bool = False):
    if logstruct:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                ProcessorFormatter.wrap_for_formatter,
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        handler = logging.StreamHandler()
        handler.setFormatter(
            ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                fmt="%(message)s",
                foreign_pre_chain=[
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            )
        )
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
        root_logger.addHandler(handler)
        root_logger.setLevel(log_level)

        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logging_logger = logging.getLogger(logger_name)
            logging_logger.handlers = []
            logging_logger.propagate = True

        log = structlog.get_logger("uvicorn")
    else:
        log = logging.getLogger("uvicorn")
        if not log.handlers and not logging.getLogger().handlers:
            logging.basicConfig(
                level=log_level, format="%(levelname)s:     %(message)s"
            )

    log.info(f"setting loglevel to: {log_level}")
    log.setLevel(log_level)
    return log


def setup_mongodb(log: logging.Logger, database: str, url: str) -> AsyncIOMotorDatabase:
    log.info("setting up mongodb client")
    pool = AsyncIOMotorClient(url)
    db = pool.get_database(database)
    log.info("setting up mongodb client, done")
    return db


def setup_oauth_providers(
    log: logging.Logger,
    http: httpx.AsyncClient,
    oauth_settings: dict["str", SettingsOAuth],
):
    oauth = OAuth()
    providers = {}
    if not oauth_settings:
        log.info("oauth not configured")
        return providers
    for provider, config in oauth_settings.items():
        if config.type == "github":
            log.info(f"oauth setting up github provider with name {provider}")
            providers[provider] = CrudOAuthGitHub(
                log=log,
                http=http,
                backend_override=config.override,
                name=provider,
                oauth=oauth,
                scope=config.scope,
                client_id=config.client.id,
                client_secret=config.client.secret,
                authorize_url=config.url.authorize,
                access_token_url=config.url.accesstoken,
                userinfo_url=config.url.userinfo,
            )
    return providers


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def cli_create_admin(
    user_id: str,
    email: str,
    name: str,
    password: str | None,
) -> None:
    log = setup_logging(settings.app.loglevel, settings.app.logstruct)
    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )
    crud_ldap = CrudLdap(
        log=log,
        ldap_base_dn=settings.ldap.basedn,
        ldap_bind_dn=settings.ldap.binddn,
        ldap_pool=None,
        ldap_url=settings.ldap.url,
        ldap_user_pattern=settings.ldap.userpattern,
    )

    crud_manager = CrudManager(log=log)
    crud_users = crud_manager.register(
        CrudUsers(
            config=settings,
            log=log,
            coll=mongo_db["users"],
            crud_ldap=crud_ldap,
        )
    )

    await crud_manager.init_all()

    try:
        await crud_users.get(_id=user_id, fields=["_id"])
        log.error(f"user {user_id} already exists")
        sys.exit(1)
    except ResourceNotFound:
        pass

    if not password:
        password = _generate_password()
        print(f"generated password for {user_id}: {password}")

    try:
        await crud_users.create(
            _id=user_id,
            payload=UserPost(
                admin=True,
                email=email,
                name=name,
                password=password,
            ),
            fields=["_id"],
        )
    except DuplicateResource:
        log.error(f"user {user_id} already exists")
        sys.exit(1)

    log.info(f"created admin user {user_id}")


def cli_init_ca_write_file(path: str, content: bytes) -> None:
    print(f"writing to {path}")
    with open(path, "wb") as f:
        f.write(content)


async def cli_init_ca(
    cn: str,
    alt_names: list[str] | None,
    ca_path: str | None,
    cert_path: str | None,
    key_path: str | None,
) -> None:
    log = setup_logging(settings.app.loglevel, settings.app.logstruct)
    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )

    nodes_data_protector = NodesDataProtector(
        app_secret_key=settings.app.secretkey,
        log=log,
    )

    crud_manager = CrudManager(log=log)

    crud_ca_authorities = crud_manager.register(
        CrudCAAuthorities(
            config=settings,
            log=log,
            coll=mongo_db["ca_authorities"],
            protector=nodes_data_protector,
        )
    )

    crud_ca_spaces = crud_manager.register(
        CrudCASpaces(
            config=settings,
            log=log,
            coll=mongo_db["ca_spaces"],
            protector=nodes_data_protector,
        )
    )

    crud_ca_certificates = crud_manager.register(
        CrudCACertificates(
            config=settings,
            log=log,
            coll=mongo_db["ca_certificates"],
        )
    )

    crud_pyppetdb_nodes = crud_manager.register(
        CrudPyppetDBNodes(
            config=settings,
            log=log,
            coll=mongo_db["pyppetdb_nodes"],
        )
    )

    await crud_manager.init_all()

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
        crud_pyppetdb_nodes=crud_pyppetdb_nodes,
    )

    await ensure_default_ca_setup(
        log=log,
        ca_service=ca_service,
    )

    csr_pem, key_pem = pyppetdb.ca.utils.CAUtils.generate_csr(
        cn=cn,
        alt_names=alt_names,
    )

    space_id = "puppet-ca"
    await ca_service.submit_certificate_request(
        space_id=space_id,
        csr_pem=csr_pem.decode(),
        fields=["id"],
        cn=cn,
    )

    cert = await ca_service.sign_certificate(
        space_id=space_id,
        cn=cn,
        fields=["certificate"],
    )

    ca_authority = await crud_ca_authorities.get(
        space_id, fields=["certificate", "chain"]
    )

    if not ca_path:
        ca_path = settings.app.main.ssl.ca if settings.app.main.ssl else None
    if not cert_path:
        cert_path = settings.app.main.ssl.cert if settings.app.main.ssl else None
    if not key_path:
        key_path = settings.app.main.ssl.key if settings.app.main.ssl else None

    if not all([ca_path, cert_path, key_path]):
        log.fatal("CA path, cert path or key path not provided and not in config")
        sys.exit(1)

    cli_init_ca_write_file(ca_path, ca_authority.certificate.encode())
    cli_init_ca_write_file(cert_path, cert.certificate.encode())
    cli_init_ca_write_file(key_path, key_pem)


async def cli_import_puppet_ca(
    ca_dir: str, ca_id: str = "puppet-ca", skip_certs: bool = False
) -> None:
    log = setup_logging(settings.app.loglevel, settings.app.logstruct)
    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )

    nodes_data_protector = NodesDataProtector(
        app_secret_key=settings.app.secretkey,
        log=log,
    )

    crud_manager = CrudManager(log=log)

    crud_ca_authorities = crud_manager.register(
        CrudCAAuthorities(
            config=settings,
            log=log,
            coll=mongo_db["ca_authorities"],
            protector=nodes_data_protector,
        )
    )

    crud_ca_spaces = crud_manager.register(
        CrudCASpaces(
            config=settings,
            log=log,
            coll=mongo_db["ca_spaces"],
            protector=nodes_data_protector,
        )
    )

    crud_ca_certificates = crud_manager.register(
        CrudCACertificates(
            config=settings,
            log=log,
            coll=mongo_db["ca_certificates"],
        )
    )

    crud_pyppetdb_nodes = crud_manager.register(
        CrudPyppetDBNodes(
            config=settings,
            log=log,
            coll=mongo_db["pyppetdb_nodes"],
        )
    )

    await crud_manager.init_all()

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
        crud_pyppetdb_nodes=crud_pyppetdb_nodes,
    )

    puppet_ca_id = ca_id
    puppet_ca_dir = Path(ca_dir)

    ca_crt_path = puppet_ca_dir / "ca_crt.pem"
    ca_key_path = puppet_ca_dir / "ca_key.pem"

    if not ca_crt_path.exists():
        log.fatal(f"CA certificate not found at {ca_crt_path}")
        sys.exit(1)
    if not ca_key_path.exists():
        log.fatal(f"CA private key not found at {ca_key_path}")
        sys.exit(1)

    ca_cert_pem = ca_crt_path.read_bytes()
    ca_key_pem = ca_key_path.read_bytes()

    try:
        await crud_ca_authorities.get(puppet_ca_id, fields=["id"])
        if puppet_ca_id == "puppet-ca":
            log.error(
                f"CA Authority '{puppet_ca_id}' already exists. Please delete it first or use --ca-id to choose a different ID."
            )
        else:
            log.error(
                f"CA Authority '{puppet_ca_id}' already exists. Please choose a different ID."
            )
        sys.exit(1)
    except ResourceNotFound:
        pass

    log.info(f"Importing CA Authority '{puppet_ca_id}' from {ca_dir}")

    ca_info = CAUtils.get_cert_info(ca_cert_pem)
    encrypted_key = nodes_data_protector.encrypt_string(ca_key_pem.decode())

    crl_pem, next_update = CAUtils.generate_crl(
        ca_cert=ca_cert_pem,
        ca_key=ca_key_pem,
        revoked_certs=[],
        validity_days=settings.ca.crlValidityDays,
    )
    now = datetime.datetime.now(datetime.timezone.utc)

    ca_authority_data = {
        "id": puppet_ca_id,
        "parent_id": None,
        "certificate": ca_cert_pem.decode(),
        "private_key_encrypted": encrypted_key,
        "internal": True,
        "chain": [],
        "status": "active",
        "crl": {
            "crl_pem": crl_pem.decode(),
            "generation": 1,
            "updated_at": now,
            "next_update": next_update,
            "locked_at": None,
        },
        **ca_info,
    }

    await crud_ca_authorities.coll.insert_one(ca_authority_data)
    log.info(f"CA Authority '{puppet_ca_id}' imported successfully.")

    try:
        await crud_ca_spaces.get("puppet-ca", fields=["id"])
        log.info(f"Updating existing CA Space 'puppet-ca' to use CA '{puppet_ca_id}'")
        from pyppetdb.model.ca_spaces import CASpacePutInternal

        await crud_ca_spaces.update(
            _id="puppet-ca",
            payload=CASpacePutInternal(ca_id=puppet_ca_id),
            fields=[],
        )
    except ResourceNotFound:
        log.info(f"Creating CA Space 'puppet-ca' for CA '{puppet_ca_id}'")
        await ca_service.create_space(
            _id="puppet-ca",
            payload=CASpacePost(ca_id=puppet_ca_id),
            fields=[],
        )

    log.info("CA Space 'puppet-ca' updated successfully.")

    if not skip_certs:
        signed_certs_dir = puppet_ca_dir / "signed"
        if signed_certs_dir.exists() and signed_certs_dir.is_dir():
            log.info(f"Importing signed certificates from {signed_certs_dir}")
            for cert_file in signed_certs_dir.glob("*.pem"):
                try:
                    cert_pem = cert_file.read_bytes()
                    cert_info = CAUtils.get_cert_info(cert_pem)
                    cn = cert_info["cn"]
                    serial_number = cert_info["serial_number"]

                    try:
                        await crud_ca_certificates.get(serial_number, fields=["id"])
                        log.warning(
                            f"Certificate with serial {serial_number} (CN: {cn}) already exists. Skipping."
                        )
                        continue
                    except ResourceNotFound:
                        pass

                    cert_data = {
                        "id": serial_number,
                        "space_id": "puppet-ca",
                        "ca_id": puppet_ca_id,
                        "cn": cn,
                        "status": "signed",
                        "certificate": cert_pem.decode(),
                        "created": cert_info["not_before"],
                        **cert_info,
                    }
                    await crud_ca_certificates.coll.insert_one(cert_data)
                    log.info(f"Imported certificate {cn} (Serial: {serial_number})")
                except Exception as e:
                    log.error(f"Failed to import certificate {cert_file.name}: {e}")
        else:
            log.info(
                f"No 'signed' directory found at {signed_certs_dir}. Skipping signed certificate import."
            )
    else:
        log.info("Skipping signed certificate import as requested.")

    log.info("Puppet CA import complete.")


app = FastAPI(
    title="pyppetdb",
    version=version,
    lifespan=lifespan,
)
app.add_middleware(
    middleware_class=SessionMiddleware,
    secret_key=settings.app.secretkey,
    max_age=3600,
)
app_dev = app


@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


async def pyppetdb_nodes_heartbeat_worker(
    crud: CrudPyppetDBNodes,
    port: int,
):
    _id = f"{socket.getfqdn()}:{port}"
    while True:
        try:
            await crud.heartbeat_update(_id=_id)
        except Exception as e:
            logging.getLogger(name="pyppetdb").error(
                msg=f"Error updating heartbeat for {_id}: {e}"
            )
        await asyncio.sleep(delay=10)


async def main_run():
    _settings = settings.app.main

    ssl_cert = None
    ssl_key = None
    ssl_ca = None
    ssl_enabled = False

    if _settings.ssl:
        ssl_enabled = True
        ssl_cert = _settings.ssl.cert
        ssl_key = _settings.ssl.key
        ssl_ca = _settings.ssl.ca

    if not ssl_enabled and settings.app.puppet.ssl:
        ssl_enabled = True
        ssl_cert = settings.app.puppet.ssl.cert
        ssl_key = settings.app.puppet.ssl.key
        ssl_ca = settings.app.puppet.ssl.ca
    elif ssl_enabled and not ssl_ca and settings.app.puppet.ssl and settings.app.puppet.ssl.ca:
        ssl_ca = settings.app.puppet.ssl.ca

    config = uvicorn.Config(
        app=app,
        host=_settings.host,
        port=_settings.port,
        log_config=None,
        ssl_ca_certs=ssl_ca,
        ssl_certfile=ssl_cert,
        ssl_keyfile=ssl_key,
        ssl_cert_reqs=ssl.CERT_OPTIONAL if ssl_enabled else ssl.CERT_NONE,
        http=ClientCertProtocol if ssl_enabled else "auto",
        ws=ClientCertWebSocketsProtocol if ssl_enabled else "auto",
    )
    server = uvicorn.Server(config=config)
    await server.serve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyppetdb")
    subparsers = parser.add_subparsers(dest="command")

    create_admin = subparsers.add_parser("create-admin", help="create an admin user")
    create_admin.add_argument("--user-id", default="admin")
    create_admin.add_argument("--email", default="admin@example.com")
    create_admin.add_argument("--name", default="admin")
    create_admin.add_argument("--password")

    init_ca = subparsers.add_parser(
        "init-ca", help="initialize the default puppet ca and generate a server cert"
    )
    fqdn = socket.getfqdn()
    init_ca.add_argument(
        "--cn",
        default=fqdn,
        help=f"The common name for the server certificate (default: {fqdn})",
    )
    init_ca.add_argument("--alt-names", help="Optional comma-separated list of SANs")
    init_ca.add_argument(
        "--ca-path",
        default="/etc/puppetlabs/puppet/ssl/certs/ca.pem",
        help="Path to save the CA certificate (default: /etc/puppetlabs/puppet/ssl/certs/ca.pem)",
    )
    init_ca.add_argument(
        "--cert-path",
        default=f"/etc/puppetlabs/puppet/ssl/certs/{fqdn}.pem",
        help=f"Path to save the server certificate (default: /etc/puppetlabs/puppet/ssl/certs/{fqdn}.pem)",
    )
    init_ca.add_argument(
        "--key-path",
        default=f"/etc/puppetlabs/puppet/ssl/private_keys/{fqdn}.pem",
        help=f"Path to save the server private key (default: /etc/puppetlabs/puppet/ssl/private_keys/{fqdn}.pem)",
    )

    import_puppet_ca = subparsers.add_parser(
        "import-puppet-ca", help="Import an existing Puppet CA into pyppetdb"
    )
    import_puppet_ca.add_argument(
        "--ca-dir",
        required=True,
        help="Path to the Puppet CA directory (e.g., /etc/puppetlabs/puppetserver/ca)",
    )
    import_puppet_ca.add_argument(
        "--ca-id",
        default="puppet-ca",
        help="ID of the CA to import (default: puppet-ca)",
    )
    import_puppet_ca.add_argument(
        "--skip-certs",
        action="store_true",
        help="Skip importing signed certificates",
    )

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "create-admin":
        asyncio.run(
            cli_create_admin(
                user_id=args.user_id,
                email=args.email,
                name=args.name,
                password=args.password,
            )
        )
        return
    elif args.command == "init-ca":
        alt_names = None
        if args.alt_names:
            alt_names = args.alt_names.split(",")
        asyncio.run(
            cli_init_ca(
                cn=args.cn,
                alt_names=alt_names,
                ca_path=args.ca_path,
                cert_path=args.cert_path,
                key_path=args.key_path,
            )
        )
        return
    elif args.command == "import-puppet-ca":
        asyncio.run(
            cli_import_puppet_ca(
                ca_dir=args.ca_dir,
                ca_id=args.ca_id,
                skip_certs=args.skip_certs,
            )
        )
        return

    asyncio.run(main_run())


if __name__ == "__main__":
    main()
