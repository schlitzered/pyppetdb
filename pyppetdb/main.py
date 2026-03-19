import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import secrets
import signal
import socket
import string
import sys
import time

from authlib.integrations.starlette_client import OAuth
import bonsai.asyncio
import httpx
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import ORJSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorDatabase
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import orjson
import pymongo

import pyppetdb.controller
import pyppetdb.controller.oauth
import pyppetdb.ca.utils

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.authorize import AuthorizePyppetDB

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
from pyppetdb.crud.oauth import CrudOAuthGitHub
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService

from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.users import UserPost

from pyppetdb.hiera import PyHiera
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.nodes_reports import NodesReportsRedactor
from pyppetdb.crud.nodes_catalogs import NodesCatalogsRedactor

from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import ResourceNotFound

version = "0.0.0"


class ORJSONRequest(Request):
    async def json(self):
        body = await self.body()
        return orjson.loads(body)


settings = Config()


async def dummy_sleep_background_task(log: logging.Logger):
    log.info("starting sleep background task")
    while True:
        await asyncio.sleep(5)
        log.info("sleeping background task")


async def ensure_default_ca_setup(
    log: logging.Logger,
    crud_ca_authorities: CrudCAAuthorities,
    crud_ca_spaces: CrudCASpaces,
):
    default_id = "puppet-ca"

    # 1. Ensure Authority exists
    try:
        await crud_ca_authorities.get(default_id, fields=["id"])
        log.info(f"Default CA Authority '{default_id}' already exists")
    except ResourceNotFound:
        log.info(f"Creating default CA Authority '{default_id}'")
        try:
            await crud_ca_authorities.create(
                _id=default_id,
                payload=CAAuthorityPost(
                    common_name="PyppetDB Internal Root CA",
                    organization="PyppetDB",
                    country="DE",
                    state="Hessen",
                    validity_days=3650,
                ),
                fields=["id"],
            )
        except DuplicateResource:
            log.info(
                f"Default CA Authority '{default_id}' was created by another process"
            )

    # 2. Ensure Space exists
    try:
        await crud_ca_spaces.get(default_id, fields=["id"])
        log.info(f"Default CA Space '{default_id}' already exists")
    except ResourceNotFound:
        log.info(f"Creating default CA Space '{default_id}'")
        try:
            await crud_ca_spaces.create(
                _id=default_id,
                payload=CASpacePost(ca_id=default_id),
                fields=["id"],
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

    http = httpx.AsyncClient()
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

    crud_nodes_credentials = CrudCredentials(
        config=settings,
        log=log,
        coll=mongo_db["nodes_credentials"],
    )
    await crud_nodes_credentials.index_create()
    env["crud_nodes_credentials"] = crud_nodes_credentials

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

    authorize_puppet = AuthorizePuppet(
        log=log,
        config=settings.app.puppet,
        crud_nodes=crud_nodes,
        crud_nodes_credentials=crud_nodes_credentials,
    )
    env["authorize_puppet"] = authorize_puppet

    authorize_pyppetdb = AuthorizePyppetDB(
        log=log,
        crud_node_groups=crud_nodes_groups,
        crud_teams=crud_teams,
        crud_users=crud_users,
        crud_users_credentials=crud_users_credentials,
    )
    env["authorize_pyppetdb"] = authorize_pyppetdb

    # Ensure default CA and Space setup
    await ensure_default_ca_setup(
        log=log,
        crud_ca_authorities=crud_ca_authorities,
        crud_ca_spaces=crud_ca_spaces,
    )

    return env


@asynccontextmanager
async def lifespan_dev(app: FastAPI):
    env = await prepare_env()

    controller = pyppetdb.controller.Controller(
        log=env["log"],
        authorize_pyppetdb=env["authorize_pyppetdb"],
        authorize_puppet=env["authorize_puppet"],
        crud_ldap=env["crud_ldap"],
        crud_hiera_key_models_static=env["crud_hiera_key_models_static"],
        crud_hiera_key_models_dynamic=env["crud_hiera_key_models_dynamic"],
        crud_hiera_keys=env["crud_hiera_keys"],
        crud_hiera_levels=env["crud_hiera_levels"],
        crud_hiera_level_data=env["crud_hiera_level_data"],
        crud_hiera_lookup_cache=env["crud_hiera_lookup_cache"],
        crud_nodes=env["crud_nodes"],
        crud_nodes_catalog_cache=env["crud_nodes_catalog_cache"],
        crud_nodes_catalogs=env["crud_nodes_catalogs"],
        crud_nodes_credentials=env["crud_nodes_credentials"],
        crud_nodes_groups=env["crud_nodes_groups"],
        crud_nodes_reports=env["crud_nodes_reports"],
        crud_nodes_secrets_redactor=env["crud_nodes_secrets_redactor"],
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
    )
    app.include_router(controller.router_dev)

    # Start CA background tasks
    refresh_task = None
    if settings.ca.enableCrlRefresh:
        refresh_task = asyncio.create_task(
            env["ca_service"].crl_refresh_worker(), name="ca-crl-refresh"
        )

    yield
    if refresh_task:
        refresh_task.cancel()


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
    common_name: str,
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

    # 1. Ensure CA and Space
    await ensure_default_ca_setup(
        log=log,
        crud_ca_authorities=crud_ca_authorities,
        crud_ca_spaces=crud_ca_spaces,
    )

    # 2. Generate CSR and Key
    csr_pem, key_pem = pyppetdb.ca.utils.CAUtils.generate_csr(
        common_name=common_name,
        alt_names=alt_names,
    )

    # 3. Submit CSR
    space_id = "puppet-ca"
    space = await crud_ca_spaces.get(space_id, fields=["ca_id"])
    await crud_ca_certificates.submit_csr(
        space_id=space_id,
        csr_pem=csr_pem.decode(),
        ca_id=space.ca_id,
        fields=["id"],
    )

    # 4. Sign CSR
    from pyppetdb.model.ca_certificates import CACertificatePut

    cert = await ca_service.update_certificate_status(
        space_id=space_id,
        cn=common_name,
        data=CACertificatePut(status="signed"),
        fields=["certificate"],
    )

    # 5. Get CA Cert
    ca_authority = await crud_ca_authorities.get(
        space_id, fields=["certificate", "chain"]
    )

    # 6. Write Files
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


app_dev = FastAPI(
    title="pyppetdb all in one dev server",
    version=version,
    lifespan=lifespan_dev,
    default_response_class=ORJSONResponse,
    request_class=ORJSONRequest,
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
        default_response_class=ORJSONResponse,
        request_class=ORJSONRequest,
    )
    app.add_middleware(
        SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
    )
    app.include_router(getattr(controller, f"router_{app_name}"))

    config = uvicorn.Config(
        app,
        host=_settings.host,
        port=_settings.port,
        ssl_ca_certs=_settings.ssl.ca if _settings.ssl else None,
        ssl_certfile=_settings.ssl.cert if _settings.ssl else None,
        ssl_keyfile=_settings.ssl.key if _settings.ssl else None,
    )
    config.install_signal_handlers = False
    return uvicorn.Server(config)


async def main_run():
    env = await prepare_env()
    log = env["log"]
    controller = pyppetdb.controller.Controller(
        log=env["log"],
        authorize_pyppetdb=env["authorize_pyppetdb"],
        authorize_puppet=env["authorize_puppet"],
        crud_ldap=env["crud_ldap"],
        crud_hiera_key_models_static=env["crud_hiera_key_models_static"],
        crud_hiera_key_models_dynamic=env["crud_hiera_key_models_dynamic"],
        crud_hiera_keys=env["crud_hiera_keys"],
        crud_hiera_levels=env["crud_hiera_levels"],
        crud_hiera_level_data=env["crud_hiera_level_data"],
        crud_hiera_lookup_cache=env["crud_hiera_lookup_cache"],
        crud_nodes=env["crud_nodes"],
        crud_nodes_catalog_cache=env["crud_nodes_catalog_cache"],
        crud_nodes_catalogs=env["crud_nodes_catalogs"],
        crud_nodes_credentials=env["crud_nodes_credentials"],
        crud_nodes_groups=env["crud_nodes_groups"],
        crud_nodes_reports=env["crud_nodes_reports"],
        crud_nodes_secrets_redactor=env["crud_nodes_secrets_redactor"],
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

    # Start CA background tasks
    worker_tasks = list()
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

        # Cancel workers and stop-event task before gathering apps
        for t in worker_tasks + [all_tasks[-1]]:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t

        # Give apps some time to stop gracefully
        try:
            await asyncio.wait_for(asyncio.gather(*apps_tasks), timeout=10)
        except asyncio.TimeoutError:
            log.warning("Apps did not stop in time, forcing shutdown...")
    finally:
        # Final cleanup of any remaining tasks
        for t in all_tasks:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t

        # Close LDAP pool if it exists
        if "ldap_pool" in env and env["ldap_pool"]:
            log.info("Closing LDAP pool...")
            await env["ldap_pool"].close()

        # Close HTTP client
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
        "--common-name",
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
                common_name=args.common_name,
                alt_names=alt_names,
                ca_path=args.ca_path,
                cert_path=args.cert_path,
                key_path=args.key_path,
            )
        )
        return

    asyncio.run(main_run())


if __name__ == "__main__":
    main()
