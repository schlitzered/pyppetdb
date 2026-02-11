import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import random
import signal
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

import pyppetdb.controller
import pyppetdb.controller.oauth

from pyppetdb.authorize import Authorize

from pyppetdb.config import Config
from pyppetdb.config import ConfigLdap as SettingsLdap
from pyppetdb.config import ConfigOAuth as SettingsOAuth

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.hiera_key_models import CrudHieraKeyModels
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.oauth import CrudOAuthGitHub
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers

from pyppetdb.model.users import UserPost

from pyppetdb.pyhiera import PyHiera

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

    crud_nodes = CrudNodes(
        config=settings,
        log=log,
        coll=mongo_db["nodes"],
    )
    await crud_nodes.index_create()
    env["crud_nodes"] = crud_nodes

    crud_nodes_catalogs = CrudNodesCatalogs(
        config=settings,
        log=log,
        coll=mongo_db["nodes_catalogs"],
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

    pyhiera = PyHiera(
        log=log,
        config=settings.hiera,
        crud_hiera_level_data=crud_hiera_level_data,
        hiera_level_ids=crud_hiera_levels.cache.level_ids,
    )
    env["pyhiera"] = pyhiera

    crud_hiera_keys = CrudHieraKeys(
        config=settings,
        log=log,
        coll=mongo_db["hiera_keys"],
        pyhiera=pyhiera,
    )
    await crud_hiera_keys.index_create()
    env["crud_hiera_keys"] = crud_hiera_keys

    crud_hiera_key_models = CrudHieraKeyModels(
        config=settings,
        log=log,
        pyhiera=pyhiera,
    )
    env["crud_hiera_key_models"] = crud_hiera_key_models

    authorize = Authorize(
        log=log,
        crud_node_groups=crud_nodes_groups,
        crud_teams=crud_teams,
        crud_users=crud_users,
        crud_users_credentials=crud_users_credentials,
    )
    env["authorize"] = authorize
    await setup_admin_user(log=log, crud_users=crud_users)
    return env


@asynccontextmanager
async def lifespan_dev(app: FastAPI):
    env = await prepare_env()

    controller = pyppetdb.controller.Controller(
        log=env["log"],
        authorize=env["authorize"],
        crud_ldap=env["crud_ldap"],
        crud_hiera_key_models=env["crud_hiera_key_models"],
        crud_hiera_keys=env["crud_hiera_keys"],
        crud_hiera_levels=env["crud_hiera_levels"],
        crud_hiera_level_data=env["crud_hiera_level_data"],
        crud_nodes=env["crud_nodes"],
        crud_nodes_catalogs=env["crud_nodes_catalogs"],
        crud_nodes_groups=env["crud_nodes_groups"],
        crud_nodes_reports=env["crud_nodes_reports"],
        crud_teams=env["crud_teams"],
        crud_users=env["crud_users"],
        crud_users_credentials=env["crud_users_credentials"],
        crud_oauth=env["crud_oauth"],
        http=env["http"],
        config=settings,
        pyhiera=env["pyhiera"],
    )
    app.include_router(controller.router_dev)
    yield


async def setup_admin_user(log: logging.Logger, crud_users: CrudUsers):
    try:
        await crud_users.get(_id="admin", fields=["_id"])
    except ResourceNotFound:
        password = "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(20)
        )
        log.info(f"creating admin user with password {password}")
        await crud_users.create(
            _id="admin",
            payload=UserPost(
                admin=True,
                email="admin@example.com",
                name="admin",
                password=password,
            ),
            fields=["_id"],
        )
        log.info("creating admin user, done")


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
    return uvicorn.Server(config)


async def main_run():
    env = await prepare_env()
    log = env["log"]
    controller = pyppetdb.controller.Controller(
        log=env["log"],
        authorize=env["authorize"],
        crud_ldap=env["crud_ldap"],
        crud_hiera_key_models=env["crud_hiera_key_models"],
        crud_hiera_keys=env["crud_hiera_keys"],
        crud_hiera_levels=env["crud_hiera_levels"],
        crud_hiera_level_data=env["crud_hiera_level_data"],
        crud_nodes=env["crud_nodes"],
        crud_nodes_catalogs=env["crud_nodes_catalogs"],
        crud_nodes_groups=env["crud_nodes_groups"],
        crud_nodes_reports=env["crud_nodes_reports"],
        crud_teams=env["crud_teams"],
        crud_users=env["crud_users"],
        crud_users_credentials=env["crud_users_credentials"],
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

    if not apps:
        log.fatal("no apps configured")
        sys.exit(1)

    stop_event = asyncio.Event()

    def request_stop():
        for _app in apps:
            _app.should_exit = True
        stop_event.set()

    apps_tasks.append(asyncio.create_task(stop_event.wait(), name="stop-event"))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)

    try:
        await asyncio.wait(
            apps_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not stop_event.is_set():
            request_stop()

        await asyncio.gather(*apps_tasks)
    finally:
        for t in apps_tasks:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t


def main():
    asyncio.run(main_run())


if __name__ == "__main__":
    main()
