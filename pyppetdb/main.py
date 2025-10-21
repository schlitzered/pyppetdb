import asyncio
from contextlib import asynccontextmanager
import logging
import random
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
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.oauth import CrudOAuthGitHub
from pyppetdb.crud.teams import CrudTeams
from pyppetdb.crud.users import CrudUsers

from pyppetdb.model.users import UserPost

from pyppetdb.errors import ResourceNotFound


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = setup_logging(
        settings.app.loglevel,
    )

    #    asyncio.create_task(dummy_sleep_background_task(log))
    log.info(settings)

    http = httpx.AsyncClient()

    ldap_pool = await setup_ldap(
        log=log,
        settings_ldap=settings.ldap,
    )

    log.info("adding routes")
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

    crud_ldap = CrudLdap(
        log=log,
        ldap_base_dn=settings.ldap.basedn,
        ldap_bind_dn=settings.ldap.binddn,
        ldap_pool=ldap_pool,
        ldap_url=settings.ldap.url,
        ldap_user_pattern=settings.ldap.userpattern,
    )

    crud_nodes = CrudNodes(
        config=settings,
        log=log,
        coll=mongo_db["nodes"],
    )
    await crud_nodes.index_create()

    crud_nodes_catalogs = CrudNodesCatalogs(
        config=settings,
        log=log,
        coll=mongo_db["nodes_catalogs"],
    )
    await crud_nodes_catalogs.index_create()

    crud_nodes_groups = CrudNodesGroups(
        config=settings,
        log=log,
        coll=mongo_db["nodes_groups"],
    )
    await crud_nodes_groups.index_create()

    crud_nodes_reports = CrudNodesReports(
        config=settings,
        log=log,
        coll=mongo_db["nodes_reports"],
    )
    await crud_nodes_reports.index_create()

    crud_teams = CrudTeams(
        config=settings,
        log=log,
        coll=mongo_db["teams"],
    )
    await crud_teams.index_create()

    crud_users = CrudUsers(
        config=settings,
        log=log,
        coll=mongo_db["users"],
        crud_ldap=crud_ldap,
    )
    await crud_users.index_create()

    crud_users_credentials = CrudCredentials(
        config=settings,
        log=log,
        coll=mongo_db["users_credentials"],
    )
    await crud_users_credentials.index_create()

    authorize = Authorize(
        log=log,
        crud_node_groups=crud_nodes_groups,
        crud_teams=crud_teams,
        crud_users=crud_users,
        crud_users_credentials=crud_users_credentials,
    )

    controller = pyppetdb.controller.Controller(
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
        crud_oauth=crud_oauth,
        http=http,
        config=settings,
    )
    app.include_router(controller.router)

    log.info("adding routes, done")
    await setup_admin_user(log=log, crud_users=crud_users)
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


app = FastAPI(
    title="pyppetdb",
    version="0.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    request_class=ORJSONRequest,
)
app.add_middleware(SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600)


@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


def main():
    if settings.app.ssl:
        uvicorn.run(
            app,
            host=settings.app.host,
            port=settings.app.port,
            ssl_certfile=settings.app.ssl.cert,
            ssl_keyfile=settings.app.ssl.key,
        )
    else:
        uvicorn.run(app, host=settings.app.host, port=settings.app.port)


if __name__ == "__main__":
    main()
