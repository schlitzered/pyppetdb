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
from contextlib import asynccontextmanager
import logging
import secrets
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

from pyppetdb.config import Config
from pyppetdb.config import ConfigLdap as SettingsLdap
from pyppetdb.config import ConfigOAuth as SettingsOAuth
from pyppetdb.crud.oauth import CrudOAuthGitHub
from pyppetdb.container import AppContainer
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import DuplicateResource
from pyppetdb.model.users import UserPost
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpacePutInternal
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.ca.utils import CAUtils

version = "0.0.0"


settings = Config()


async def prepare_env() -> AppContainer:
    log = setup_logging(
        log_level=settings.app.loglevel,
        logstruct=settings.app.logstruct,
    )
    log.info(msg=settings)

    http = httpx.AsyncClient(
        timeout=60,
    )

    ldap_pool = await setup_ldap(
        log=log,
        settings_ldap=settings.ldap,
    )

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

    container = AppContainer(
        config=settings,
        log=log,
        mongo_db=mongo_db,
        http=http,
        ldap_pool=ldap_pool,
        crud_oauth=crud_oauth,
    )
    await container.init()
    return container


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await prepare_env()

    controller = pyppetdb.controller.Controller(
        log=container.log,
        authorize_pyppetdb=container.authorize_pyppetdb,
        authorize_client_cert_puppet=container.authorize_client_cert_puppet,
        authorize_client_cert_pdb=container.authorize_client_cert_pdb,
        crud_ldap=container.crud_ldap,
        crud_hiera_key_models_static=container.crud_hiera_key_models_static,
        crud_hiera_key_models_dynamic=container.crud_hiera_key_models_dynamic,
        crud_hiera_keys=container.crud_hiera_keys,
        crud_hiera_levels=container.crud_hiera_levels,
        crud_hiera_level_data=container.crud_hiera_level_data,
        crud_hiera_lookup_cache=container.crud_hiera_lookup_cache,
        crud_job_definitions=container.crud_job_definitions,
        crud_jobs=container.crud_jobs,
        crud_node_jobs=container.crud_node_jobs,
        crud_nodes=container.crud_nodes,
        crud_nodes_catalog_cache=container.crud_nodes_catalog_cache,
        crud_nodes_catalogs=container.crud_nodes_catalogs,
        crud_nodes_groups=container.crud_nodes_groups,
        crud_nodes_reports=container.crud_nodes_reports,
        crud_nodes_secrets_redactor=container.crud_nodes_secrets_redactor,
        crud_pyppetdb_nodes=container.crud_pyppetdb_nodes,
        crud_teams=container.crud_teams,
        crud_users=container.crud_users,
        crud_users_credentials=container.crud_users_credentials,
        crud_ca_authorities=container.crud_ca_authorities,
        crud_ca_spaces=container.crud_ca_spaces,
        crud_ca_certificates=container.crud_ca_certificates,
        ca_service=container.ca_service,
        crud_oauth=container.crud_oauth,
        http=container.http,
        config=settings,
        pyhiera=container.pyhiera,
        redactor=container.nodes_secrets_redactor,
        ws_hub=container.ws_hub,
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
            crud=container.crud_pyppetdb_nodes,
            port=settings.app.main.port,
        ),
        name="pyppetdb-nodes-heartbeat",
    )
    expire_jobs_task = asyncio.create_task(
        coro=container.job_service.expire_scheduled_jobs_worker(),
        name="expire-scheduled-jobs",
    )
    ws_hub_task = asyncio.create_task(
        coro=container.ws_hub.run(),
        name="ws-hub-background",
    )
    if settings.ca.enableCrlRefresh:
        refresh_task = asyncio.create_task(
            coro=container.ca_service.crl_refresh_worker(),
            name="ca-crl-refresh",
        )

    yield

    heartbeat_task.cancel()
    expire_jobs_task.cancel()
    container.ws_hub.stop()
    ws_hub_task.cancel()
    if refresh_task:
        refresh_task.cancel()

    await container.close()


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
    container = await prepare_env()
    log = container.log

    try:
        await container.crud_users.get(
            _id=user_id,
            fields=["_id"],
        )
        log.error(msg=f"user {user_id} already exists")
        sys.exit(1)
    except ResourceNotFound:
        pass

    if not password:
        password = _generate_password()
        print(f"generated password for {user_id}: {password}")

    try:
        await container.crud_users.create(
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
        log.error(msg=f"user {user_id} already exists")
        sys.exit(1)

    log.info(msg=f"created admin user {user_id}")


def cli_init_ca_write_file(path: str, content: bytes) -> None:
    print(f"writing to {path}")
    Path(path).write_bytes(content)


async def cli_init_ca(
    cn: str,
    alt_names: list[str] | None,
    ca_path: str | None,
    cert_path: str | None,
    key_path: str | None,
) -> None:
    container = await prepare_env()
    log = container.log

    csr_pem, key_pem = CAUtils.generate_csr(
        cn=cn,
        alt_names=alt_names,
    )

    space_id = "puppet-ca"
    await container.ca_service.submit_certificate_request(
        space_id=space_id,
        csr_pem=csr_pem.decode(),
        fields=["id"],
        cn=cn,
    )

    cert = await container.ca_service.sign_certificate(
        space_id=space_id,
        cn=cn,
        fields=["certificate"],
    )

    ca_authority = await container.crud_ca_authorities.get(
        _id=space_id,
        fields=["certificate", "chain"],
    )

    _ssl = settings.app.main.ssl
    ca_path = ca_path or (_ssl.ca if _ssl else None)
    cert_path = cert_path or (_ssl.cert if _ssl else None)
    key_path = key_path or (_ssl.key if _ssl else None)

    if not all([ca_path, cert_path, key_path]):
        log.fatal(msg="CA path, cert path or key path not provided and not in config")
        sys.exit(1)

    cli_init_ca_write_file(
        path=ca_path,
        content=ca_authority.certificate.encode(),
    )
    cli_init_ca_write_file(
        path=cert_path,
        content=cert.certificate.encode(),
    )
    cli_init_ca_write_file(
        path=key_path,
        content=key_pem,
    )


async def cli_import_puppet_ca(
    ca_dir: str,
    ca_id: str = "puppet-ca",
    skip_certs: bool = False,
) -> None:
    container = await prepare_env()
    log = container.log

    ca_dir = Path(ca_dir)

    ca_crt_path = ca_dir / "ca_crt.pem"
    ca_key_path = ca_dir / "ca_key.pem"

    if not ca_crt_path.exists():
        log.fatal(msg=f"CA certificate not found at {ca_crt_path}")
        sys.exit(1)
    if not ca_key_path.exists():
        log.fatal(msg=f"CA private key not found at {ca_key_path}")
        sys.exit(1)

    ca_cert_pem = ca_crt_path.read_bytes()
    ca_key_pem = ca_key_path.read_bytes()

    try:
        await container.crud_ca_authorities.get(
            _id=ca_id,
            fields=["id"],
        )
        if ca_id == "puppet-ca":
            log.error(
                msg=f"CA Authority '{ca_id}' already exists. Please delete it first or use --ca-id to choose a different ID."
            )
        else:
            log.error(
                msg=f"CA Authority '{ca_id}' already exists. Please choose a different ID."
            )
        sys.exit(1)
    except ResourceNotFound:
        pass

    log.info(msg=f"Importing CA Authority '{ca_id}' from {ca_dir}")

    ca_info = CAUtils.get_cert_info(cert_pem=ca_cert_pem)
    encrypted_key = container.nodes_data_protector.encrypt_string(
        cleartext=ca_key_pem.decode(),
    )

    crl_pem, next_update = CAUtils.generate_crl(
        ca_cert=ca_cert_pem,
        ca_key=ca_key_pem,
        revoked_certs=[],
        validity_days=settings.ca.crlValidityDays,
    )
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    ca_authority_data = {
        "id": ca_id,
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

    await container.crud_ca_authorities.coll.insert_one(document=ca_authority_data)
    log.info(msg=f"CA Authority '{ca_id}' imported successfully.")

    try:
        await container.crud_ca_spaces.get(
            _id="puppet-ca",
            fields=["id"],
        )
        log.info(msg=f"Updating existing CA Space 'puppet-ca' to use CA '{ca_id}'")
        await container.crud_ca_spaces.update(
            _id="puppet-ca",
            payload=CASpacePutInternal(
                ca_id=ca_id,
            ),
            fields=[],
        )
    except ResourceNotFound:
        log.info(msg=f"Creating CA Space 'puppet-ca' for CA '{ca_id}'")
        await container.ca_service.create_space(
            _id="puppet-ca",
            payload=CASpacePost(
                ca_id=ca_id,
            ),
            fields=[],
        )

    log.info(msg="CA Space 'puppet-ca' updated successfully.")

    if not skip_certs:
        signed_certs_dir = ca_dir / "signed"
        if signed_certs_dir.exists() and signed_certs_dir.is_dir():
            log.info(msg=f"Importing signed certificates from {signed_certs_dir}")
            for cert_file in signed_certs_dir.glob("*.pem"):
                try:
                    cert_pem = cert_file.read_bytes()
                    cert_info = CAUtils.get_cert_info(cert_pem=cert_pem)
                    cn = cert_info["cn"]
                    serial_number = cert_info["serial_number"]

                    try:
                        await container.crud_ca_certificates.get(
                            _id=serial_number,
                            fields=["id"],
                        )
                        log.warning(
                            msg=f"Certificate with serial {serial_number} (CN: {cn}) already exists. Skipping."
                        )
                        continue
                    except ResourceNotFound:
                        pass

                    cert_data = {
                        "id": serial_number,
                        "space_id": "puppet-ca",
                        "ca_id": ca_id,
                        "cn": cn,
                        "status": "signed",
                        "certificate": cert_pem.decode(),
                        "created": cert_info["not_before"],
                        **cert_info,
                    }
                    await container.crud_ca_certificates.coll.insert_one(
                        document=cert_data
                    )
                    log.info(msg=f"Imported certificate {cn} (Serial: {serial_number})")
                except Exception as e:
                    log.error(msg=f"Failed to import certificate {cert_file.name}: {e}")
        else:
            log.info(
                msg=f"No 'signed' directory found at {signed_certs_dir}. Skipping signed certificate import."
            )
    else:
        log.info(msg="Skipping signed certificate import as requested.")

    log.info(msg="Puppet CA import complete.")


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


async def main_run(reload: bool = False):
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

    kwargs = dict(
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

    if reload:
        uvicorn.run(
            app="pyppetdb.main:app",
            reload=True,
            **kwargs,
        )
        return

    config = uvicorn.Config(app=app, **kwargs)
    server = uvicorn.Server(config=config)
    await server.serve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyppetdb")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload",
    )
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

    try:
        asyncio.run(main_run(reload=args.reload))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
