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
from pyppetdb.ws.manager import WsManager
from pyppetdb.ws.inter_api import WsInterAPI
from pyppetdb.ws.remote_executor import WSRemoteExecutor
from pyppetdb.ws.logs import WSLogs


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
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._redactor = redactor
        self._ws_manager = WsManager(
            log=log,
            config=config,
            crud_nodes=crud_nodes,
            crud_node_jobs=crud_node_jobs,
            crud_pyppetdb_nodes=crud_pyppetdb_nodes,
        )
        self._log = log
        self._router = APIRouter(tags=["websocket"])
        self._via = socket.getfqdn()

        self._ws_inter_api = WsInterAPI(
            log=log,
            authorize_client_cert=authorize_client_cert,
            crud_pyppetdb_nodes=crud_pyppetdb_nodes,
            ws_manager=self._ws_manager,
        )
        self._ws_remote_executor = WSRemoteExecutor(
            log=log,
            authorize_client_cert=authorize_client_cert,
            crud_nodes=crud_nodes,
            crud_jobs=crud_jobs,
            crud_job_definitions=crud_job_definitions,
            crud_node_jobs=crud_node_jobs,
            redactor=redactor,
            ws_manager=self._ws_manager,
            via=self._via,
        )
        self._ws_logs = WSLogs(
            log=log,
            config=config,
            ws_manager=self._ws_manager,
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

    async def get_ws_token(
        self,
        request: Request,
    ):
        user = await self._authorize.require_user(request=request)
        serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey,
            salt="ws-auth",
        )
        token = serializer.dumps(obj={"user_id": user.id})
        return {"token": token}

    async def remote_executor_endpoint(
        self,
        websocket: WebSocket,
        node_id: str,
    ):
        await self._ws_remote_executor.endpoint(
            websocket=websocket,
            node_id=node_id,
        )

    async def logs_endpoint(
        self,
        websocket: WebSocket,
    ):
        await self._ws_logs.endpoint(websocket=websocket)

    async def inter_api_endpoint(
        self,
        websocket: WebSocket,
    ):
        await self._ws_inter_api.endpoint(websocket=websocket)
