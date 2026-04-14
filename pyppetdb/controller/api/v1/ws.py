import logging
import socket
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pyppetdb.authorize import AuthorizePyppetDB, AuthorizeClientCert
from pyppetdb.errors import ClientCertError
from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.jobs_nodes_jobs_logs import CrudJobsNodesLogsLogBlobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.controller.api.v1.remote_executor_protocol import RemoteExecutorProtocol

html = """
<!DOCTYPE html>
<html>
    <head><title>Chat</title></head>
    <body>
        <h1>WebSocket Chat</h1>
        <form action="" onsubmit="sendMessage(event)">
            <input type="text" id="messageText" autocomplete="off"/>
            <button>Send</button>
        </form>
        <ul id='messages'></ul>
        <script>
            var client_id = Date.now()
            var ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            var ws_url = `${ws_protocol}//${window.location.host}/api/v1/ws/chat/${client_id}`;
            console.log("Connecting to: " + ws_url);
            var ws = new WebSocket(ws_url);
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                message.textContent = event.data
                messages.appendChild(message)
            };
            function sendMessage(event) {
                var input = document.getElementById("messageText")
                ws.send(input.value)
                input.value = ''
                event.preventDefault()
            }
        </script>
    </body>
</html>
"""


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


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
        crud_log_blobs: CrudJobsNodesLogsLogBlobs,
        redactor: NodesSecretsRedactor,
    ):
        self._authorize = authorize
        self._authorize_client_cert = authorize_client_cert
        self._config = config
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._crud_log_blobs = crud_log_blobs
        self._redactor = redactor
        self._conns = ConnectionManager()
        self._log = log
        self._router = APIRouter(tags=["websocket"])
        self._via = socket.getfqdn()

        self.router.add_api_route("/ws/", self.get, methods=["GET"])
        self.router.add_api_websocket_route(
            "/ws/chat/{client_id}", self.websocket_endpoint
        )
        self.router.add_api_websocket_route(
            "/ws/remote_executor/{node_id}", self.remote_executor_endpoint
        )

    @property
    def router(self):
        return self._router

    @staticmethod
    def get():
        return HTMLResponse(html)

    async def remote_executor_endpoint(self, websocket: WebSocket, node_id: str):
        try:
            await websocket.accept()
            await self._authorize_client_cert.require_cn_match(
                request=websocket, match=node_id
            )

            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id, connected=True, via=self._via
            )

            protocol = RemoteExecutorProtocol(
                log=self._log,
                node_id=node_id,
                websocket=websocket,
                crud_nodes=self._crud_nodes,
                crud_jobs=self._crud_jobs,
                crud_job_definitions=self._crud_job_definitions,
                crud_node_jobs=self._crud_node_jobs,
                crud_log_blobs=self._crud_log_blobs,
                redactor=self._redactor,
            )
            await protocol.run()

        except ClientCertError as e:
            self._log.error(f"WS remote_executor Auth failed: {e.detail}")
            await websocket.close(code=4003)
        except WebSocketDisconnect:
            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id, connected=False, via=None
            )
        except Exception as e:
            self._log.error(f"WS remote_executor unexpected error: {e}")
            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id, connected=False, via=None
            )
            await websocket.close(code=4003)

    async def websocket_endpoint(self, websocket: WebSocket, client_id: str):
        await self._conns.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await self._conns.send_personal_message(f"You wrote: {data}", websocket)
                await self._conns.broadcast(f"Client #{client_id} says: {data}")
        except WebSocketDisconnect:
            self._conns.disconnect(websocket)
            await self._conns.broadcast(f"Client #{client_id} left the chat")
        except Exception:
            self._conns.disconnect(websocket)
