import logging
import socket

from fastapi import APIRouter, WebSocket, Request
from itsdangerous import URLSafeTimedSerializer

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.ws.hub import WsHub


class ControllerApiV1Ws:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        authorize: AuthorizePyppetDB,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes: CrudNodes,
        crud_jobs: CrudJobs,
        crud_job_definitions: CrudJobsDefinitions,
        crud_node_jobs: CrudJobsNodeJobs,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        redactor: NodesSecretsRedactor,
    ):
        self._authorize = authorize
        self._authorize_client_cert = authorize_client_cert
        self._config = config
        self._log = log
        self._router = APIRouter(tags=["websocket"])

        self._ws_hub = WsHub(
            log=log,
            config=config,
            crud_nodes=crud_nodes,
            crud_jobs=crud_jobs,
            crud_job_definitions=crud_job_definitions,
            crud_node_jobs=crud_node_jobs,
            crud_pyppetdb_nodes=crud_pyppetdb_nodes,
            redactor=redactor,
            authorize_client_cert=authorize_client_cert,
        )

        self.router.add_api_route(
            "/ws/token",
            self.get_ws_token,
            methods=["POST"],
        )
        self.router.add_api_websocket_route(
            "/ws/remote_executor/{node_id}",
            self.remote_executor_endpoint,
        )
        self.router.add_api_websocket_route(
            "/ws/logs/",
            self.logs_endpoint,
        )
        self.router.add_api_websocket_route(
            "/ws/inter_api/",
            self.inter_api_endpoint,
        )

    @property
    def router(self):
        return self._router

    @property
    def ws_hub(self):
        return self._ws_hub

    async def get_ws_token(
        self,
        request: Request,
    ):
        user = await self._authorize.require_user(request=request)
        serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey,
            salt=self._config.app.wssalt,
        )
        token = serializer.dumps(obj={"user_id": user.id})
        return {"token": token}

    async def remote_executor_endpoint(
        self,
        websocket: WebSocket,
        node_id: str,
    ):
        await self.ws_hub.remote_executor.endpoint(
            websocket=websocket,
            node_id=node_id,
        )

    async def logs_endpoint(
        self,
        websocket: WebSocket,
    ):
        await self.ws_hub.api.endpoint(websocket=websocket)

    async def inter_api_endpoint(
        self,
        websocket: WebSocket,
    ):
        await self.ws_hub.inter_api.endpoint(websocket=websocket)
