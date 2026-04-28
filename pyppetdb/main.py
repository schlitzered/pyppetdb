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
    hub: WsHub,
):
    log.info("starting scheduled jobs expiration worker")
    while True:
        try:
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
        except Exception as e:
            log.error(f"Error in scheduled jobs expiration worker: {e}")

        await asyncio.sleep(60)


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
            )
        except DuplicateResource:
            log.info(f"Default CA Space '{default_id}' was created by another process")


async def prepare_env():
    env = dict()
    log = setup_logging(
        settings.app.loglevel,
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

    crud_hiera_levels = CrudHieraLevels(
        config=settings,
        log=log,
        coll=mongo_db["hiera_levels"],
    )
    await crud_hiera_levels.index_create()
    env["crud_hiera_levels"] = crud_hiera_levels

    crud_hiera_level_data = CrudHieraLevelData(
        config=settings,
        log=log,
        coll=mongo_db["hiera_level_data"],
    )
    await crud_hiera_level_data.index_create()
    env["crud_hiera_level_data"] = crud_hiera_level_data

    crud_hiera_lookup_cache = CrudHieraLookupCache(
        config=settings,
        log=log,
        coll=mongo_db["hiera_lookup_cache"],
    )
    await crud_hiera_lookup_cache.index_create()
    env["crud_hiera_lookup_cache"] = crud_hiera_lookup_cache

    crud_job_definitions = CrudJobsDefinitions(
        config=settings,
        log=log,
        coll=mongo_db["jobs_definitions"],
    )
    await crud_job_definitions.index_create()
    env["crud_job_definitions"] = crud_job_definitions

    crud_node_jobs = CrudJobsNodeJobs(
        config=settings,
        log=log,
        coll=mongo_db["jobs_node_jobs"],
    )
    await crud_node_jobs.index_create()
    env["crud_node_jobs"] = crud_node_jobs

    crud_jobs = CrudJobs(
        config=settings,
        log=log,
        coll=mongo_db["jobs"],
    )
    await crud_jobs.index_create()
    env["crud_jobs"] = crud_jobs

    crud_nodes_catalog_cache = CrudNodesCatalogCache(
        config=settings,
        log=log,
        coll=mongo_db["nodes_catalog_cache"],
        protector=nodes_data_protector,
    )
    await crud_nodes_catalog_cache.index_create()
    env["crud_nodes_catalog_cache"] = crud_nodes_catalog_cache

    crud_nodes = CrudNodes(
        config=settings,
        log=log,
        coll=mongo_db["nodes"],
    )
    await crud_nodes.index_create()
    env["crud_nodes"] = crud_nodes

    crud_nodes_secrets_redactor = CrudNodesSecretsRedactor(
        config=settings,
        log=log,
        coll=mongo_db["nodes_secrets_redactor"],
        redactor=nodes_secrets_redactor,
    )
    await crud_nodes_secrets_redactor.index_create()
    env["crud_nodes_secrets_redactor"] = crud_nodes_secrets_redactor

    crud_nodes_catalogs = CrudNodesCatalogs(
        config=settings,
        log=log,
        coll=mongo_db["nodes_catalogs"],
        secret_manager=nodes_catalogs_redactor,
    )
    await crud_nodes_catalogs.index_create()
    env["crud_nodes_catalogs"] = crud_nodes_catalogs

    crud_nodes_groups = CrudNodesGroups(
        config=settings,
        log=log,
        coll=mongo_db["nodes_groups"],
    )
    await crud_nodes_groups.index_create()
    env["crud_nodes_groups"] = crud_nodes_groups

    crud_nodes_reports = CrudNodesReports(
        config=settings,
        log=log,
        coll=mongo_db["nodes_reports"],
        secret_manager=nodes_reports_redactor,
    )
    await crud_nodes_reports.index_create()
    env["crud_nodes_reports"] = crud_nodes_reports

    crud_pyppetdb_nodes = CrudPyppetDBNodes(
        config=settings,
        log=log,
        coll=mongo_db["pyppetdb_nodes"],
    )
    await crud_pyppetdb_nodes.index_create()
    env["crud_pyppetdb_nodes"] = crud_pyppetdb_nodes

    crud_teams = CrudTeams(
        config=settings,
        log=log,
        coll=mongo_db["teams"],
    )
    await crud_teams.index_create()
    env["crud_teams"] = crud_teams

    crud_users = CrudUsers(
        config=settings,
        log=log,
        coll=mongo_db["users"],
        crud_ldap=crud_ldap,
    )
    await crud_users.index_create()
    env["crud_users"] = crud_users

    crud_users_credentials = CrudCredentials(
        config=settings,
        log=log,
        coll=mongo_db["users_credentials"],
    )
    await crud_users_credentials.index_create()
    env["crud_users_credentials"] = crud_users_credentials

    crud_ca_authorities = CrudCAAuthorities(
        config=settings,
        log=log,
        coll=mongo_db["ca_authorities"],
        protector=nodes_data_protector,
    )
    await crud_ca_authorities.index_create()
    env["crud_ca_authorities"] = crud_ca_authorities

    crud_ca_spaces = CrudCASpaces(
        config=settings,
        log=log,
        coll=mongo_db["ca_spaces"],
    )
    await crud_ca_spaces.index_create()
    env["crud_ca_spaces"] = crud_ca_spaces

    crud_ca_certificates = CrudCACertificates(
        config=settings,
        log=log,
        coll=mongo_db["ca_certificates"],
    )
    await crud_ca_certificates.index_create()
    env["crud_ca_certificates"] = crud_ca_certificates

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
    )
    env["ca_service"] = ca_service

    authorize_client_cert_puppet = AuthorizeClientCert(
        log=log,
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
        config=settings.hiera,
        crud_hiera_level_data=crud_hiera_level_data,
        hiera_level_ids=crud_hiera_levels.cache.level_ids,
    )
    env["pyhiera"] = pyhiera

    crud_hiera_key_models_dynamic = CrudHieraKeyModelsDynamic(
        config=settings,
        log=log,
        coll=mongo_db["hiera_key_models_dynamic"],
        pyhiera=pyhiera,
    )
    await crud_hiera_key_models_dynamic.index_create()
    env["crud_hiera_key_models_dynamic"] = crud_hiera_key_models_dynamic

    crud_hiera_keys = CrudHieraKeys(
        config=settings,
        log=log,
        coll=mongo_db["hiera_keys"],
        pyhiera=pyhiera,
    )
    await crud_hiera_keys.index_create()
    env["crud_hiera_keys"] = crud_hiera_keys

    crud_hiera_key_models_static = CrudHieraKeyModelsStatic(
        config=settings,
        log=log,
        pyhiera=pyhiera,
    )
    env["crud_hiera_key_models_static"] = crud_hiera_key_models_static

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
async def lifespan_dev(app: FastAPI):
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
    app.include_router(controller.router_dev)

    refresh_task = None
    heartbeat_task = asyncio.create_task(
        pyppetdb_nodes_heartbeat_worker(env["crud_pyppetdb_nodes"]),
        name="pyppetdb-nodes-heartbeat",
    )
    expire_jobs_task = asyncio.create_task(
        expire_scheduled_jobs_worker(
            log=env["log"],
            config=settings,
            crud_node_jobs=env["crud_node_jobs"],
            hub=env["ws_hub"],
        ),
        name="expire-scheduled-jobs",
    )
    ws_hub_task = asyncio.create_task(
        env["ws_hub"].run(),
        name="ws-hub-background",
    )
    if settings.ca.enableCrlRefresh:
        refresh_task = asyncio.create_task(
            env["ca_service"].crl_refresh_worker(), name="ca-crl-refresh"
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

    await env["crud_nodes"].cleanup_remote_agents(via=socket.getfqdn())


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


def setup_logging(log_level):
    log = logging.getLogger("uvicorn")
    if not log.handlers and not logging.getLogger().handlers:
        logging.basicConfig(level=log_level, format="%(levelname)s:     %(message)s")
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
    log = setup_logging(settings.app.loglevel)
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
    crud_users = CrudUsers(
        config=settings,
        log=log,
        coll=mongo_db["users"],
        crud_ldap=crud_ldap,
    )

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
    log = setup_logging(settings.app.loglevel)
    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )

    nodes_data_protector = NodesDataProtector(
        app_secret_key=settings.app.secretkey,
        log=log,
    )

    crud_ca_authorities = CrudCAAuthorities(
        config=settings,
        log=log,
        coll=mongo_db["ca_authorities"],
        protector=nodes_data_protector,
    )
    await crud_ca_authorities.index_create()

    crud_ca_spaces = CrudCASpaces(
        config=settings,
        log=log,
        coll=mongo_db["ca_spaces"],
    )
    await crud_ca_spaces.index_create()

    crud_ca_certificates = CrudCACertificates(
        config=settings,
        log=log,
        coll=mongo_db["ca_certificates"],
    )
    await crud_ca_certificates.index_create()

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
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


async def cli_import_puppet_ca(ca_dir: str) -> None:
    log = setup_logging(settings.app.loglevel)
    mongo_db = setup_mongodb(
        log=log,
        database=settings.mongodb.database,
        url=settings.mongodb.url,
    )

    nodes_data_protector = NodesDataProtector(
        app_secret_key=settings.app.secretkey,
        log=log,
    )

    crud_ca_authorities = CrudCAAuthorities(
        config=settings,
        log=log,
        coll=mongo_db["ca_authorities"],
        protector=nodes_data_protector,
    )
    await crud_ca_authorities.index_create()

    crud_ca_spaces = CrudCASpaces(
        config=settings,
        log=log,
        coll=mongo_db["ca_spaces"],
    )
    await crud_ca_spaces.index_create()

    crud_ca_certificates = CrudCACertificates(
        config=settings,
        log=log,
        coll=mongo_db["ca_certificates"],
    )
    await crud_ca_certificates.index_create()

    ca_service = CAService(
        log=log,
        config=settings,
        crud_authorities=crud_ca_authorities,
        crud_spaces=crud_ca_spaces,
        crud_certificates=crud_ca_certificates,
    )

    puppet_ca_id = "puppet-ca"
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
        log.error(
            f"CA Authority '{puppet_ca_id}' already exists. Please delete it first or choose a different ID."
        )
        sys.exit(1)
    except ResourceNotFound:
        pass

    log.info(f"Importing CA Authority '{puppet_ca_id}' from {ca_dir}")

    ca_info = CAUtils.get_cert_info(ca_cert_pem)
    encrypted_key = nodes_data_protector.encrypt_string(ca_key_pem.decode())

    crl_pem, next_update = CAUtils.generate_crl(
        ca_cert_pem=ca_cert_pem,
        ca_key_pem=ca_key_pem,
        revoked_certs=[],
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
        await crud_ca_spaces.get(puppet_ca_id, fields=["id"])
        log.error(
            f"CA Space '{puppet_ca_id}' already exists. Please delete it first or choose a different ID."
        )
        sys.exit(1)
    except ResourceNotFound:
        pass

    log.info(f"Creating CA Space '{puppet_ca_id}'")
    await ca_service.create_space(
        _id=puppet_ca_id,
        payload=CASpacePost(ca_id=puppet_ca_id),
    )
    log.info(f"CA Space '{puppet_ca_id}' created successfully.")

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
                    "space_id": puppet_ca_id,
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

    log.info("Puppet CA import complete.")


app_dev = FastAPI(
    title="pyppetdb all in one dev server",
    version=version,
    lifespan=lifespan_dev,
)
app_dev.add_middleware(
    SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
)


@app_dev.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


def main_run_get_app(
    app_name: str,
    controller: pyppetdb.controller.Controller,
) -> uvicorn.Server | None:
    _settings = getattr(settings.app, f"{app_name}")
    if not _settings.enable:
        return None
    app = FastAPI(
        title=f"pyppetdb {app_name} server",
        version=version,
    )
    app.add_middleware(
        SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
    )
    app.include_router(getattr(controller, f"router_{app_name}"))

    ssl_ca = _settings.ssl.ca if _settings.ssl else None
    if not ssl_ca and _settings.ssl and app_name == "main":
        if settings.app.puppet.ssl and settings.app.puppet.ssl.ca:
            ssl_ca = settings.app.puppet.ssl.ca

    config = uvicorn.Config(
        app,
        host=_settings.host,
        port=_settings.port,
        ssl_ca_certs=ssl_ca,
        ssl_certfile=_settings.ssl.cert if _settings.ssl else None,
        ssl_keyfile=_settings.ssl.key if _settings.ssl else None,
        ssl_cert_reqs=ssl.CERT_OPTIONAL if _settings.ssl else ssl.CERT_NONE,
        http=ClientCertProtocol if _settings.ssl else "auto",
        ws=ClientCertWebSocketsProtocol if _settings.ssl else "auto",
    )
    config.install_signal_handlers = False
    return uvicorn.Server(config)


async def pyppetdb_nodes_heartbeat_worker(crud: CrudPyppetDBNodes):
    _id = socket.getfqdn()
    while True:
        try:
            await crud.heartbeat_update(_id=_id)
        except Exception as e:
            logging.getLogger("pyppetdb").error(
                f"Error updating heartbeat for {_id}: {e}"
            )
        await asyncio.sleep(10)


async def main_run():
    env = await prepare_env()
    log = env["log"]
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
    apps = list()
    apps_tasks = list()
    for app_name in ("main", "puppet", "puppetdb"):
        app = main_run_get_app(app_name, controller)
        if app:
            apps.append(app)
            apps_tasks.append(
                asyncio.create_task(app.serve(), name=f"uvicorn-{app_name}")
            )

    worker_tasks = list()
    worker_tasks.append(
        asyncio.create_task(
            pyppetdb_nodes_heartbeat_worker(env["crud_pyppetdb_nodes"]),
            name="pyppetdb-nodes-heartbeat",
        )
    )
    worker_tasks.append(
        asyncio.create_task(
            expire_scheduled_jobs_worker(
                log=env["log"],
                config=settings,
                crud_node_jobs=env["crud_node_jobs"],
                hub=env["ws_hub"],
            ),
            name="expire-scheduled-jobs",
        )
    )
    worker_tasks.append(
        asyncio.create_task(
            env["ws_hub"].run(),
            name="ws-hub-background",
        )
    )
    if settings.ca.enableCrlRefresh:
        worker_tasks.append(
            asyncio.create_task(
                env["ca_service"].crl_refresh_worker(), name="ca-crl-refresh"
            )
        )

    if not apps:
        log.fatal("no apps configured")
        sys.exit(1)

    stop_event = asyncio.Event()

    def request_stop():
        log.info("Shutdown requested, stopping apps...")
        for _app in apps:
            _app.should_exit = True
        stop_event.set()

    all_tasks = (
        apps_tasks
        + worker_tasks
        + [asyncio.create_task(stop_event.wait(), name="stop-event")]
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)

    try:
        await asyncio.wait(
            all_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not stop_event.is_set():
            request_stop()

        env["ws_hub"].stop()

        for t in worker_tasks + [all_tasks[-1]]:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t

        try:
            await asyncio.wait_for(asyncio.gather(*apps_tasks), timeout=10)
        except asyncio.TimeoutError:
            log.warning("Apps did not stop in time, forcing shutdown...")
    finally:
        for t in all_tasks:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t
        await env["crud_nodes"].cleanup_remote_agents(via=socket.getfqdn())

        if "ldap_pool" in env and env["ldap_pool"]:
            log.info("Closing LDAP pool...")
            await env["ldap_pool"].close()

        if "http" in env and env["http"]:
            log.info("Closing HTTP client...")
            await env["http"].aclose()

        log.info("Shutdown complete.")


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
            )
        )
        return

    asyncio.run(main_run())


if __name__ == "__main__":
    main()
