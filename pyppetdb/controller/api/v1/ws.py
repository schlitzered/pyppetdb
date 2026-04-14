import logging
import socket
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pyppetdb.authorize import AuthorizePyppetDB, AuthorizeClientCert
from pyppetdb.errors import ClientCertError
from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.jobs_nodes_jobs_logs import CrudJobsNodesLogsLogBlobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.controller.api.v1.remote_executor_protocol import RemoteExecutorProtocol
from pyppetdb.controller.api.v1.ws_manager import LogSubscriptionManager
from pyppetdb.model.ws import WsMessage
from datetime import datetime

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
        self._crud_log_blobs = crud_log_blobs
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._redactor = redactor
        self._conns = ConnectionManager()
        self._ws_manager = LogSubscriptionManager(
            log=log,
            config=config,
            crud_nodes=crud_nodes,
            crud_node_jobs=crud_node_jobs,
            crud_log_blobs=crud_log_blobs,
            crud_pyppetdb_nodes=crud_pyppetdb_nodes,
        )
        self._log = log
        self._router = APIRouter(tags=["websocket"])
        self._via = socket.getfqdn()

        self.router.add_api_route("/ws/", self.get, methods=["GET"])
        self.router.add_api_route("/ws/token", self.get_ws_token, methods=["POST"])
        self.router.add_api_websocket_route(
            "/ws/chat/{client_id}", self.websocket_endpoint
        )
        self.router.add_api_websocket_route(
            "/ws/remote_executor/{node_id}", self.remote_executor_endpoint
        )
        self.router.add_api_websocket_route("/ws/logs/", self.logs_endpoint)
        self.router.add_api_websocket_route("/ws/inter_api/", self.inter_api_endpoint)

    @property
    def router(self):
        return self._router

    @staticmethod
    def get():
        return HTMLResponse(html)

    async def get_ws_token(self, request: Request):
        user = await self._authorize.require_user(request=request)
        serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey, salt="ws-auth"
        )
        token = serializer.dumps({"user_id": user.id})
        return {"token": token}

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
                manager=self._ws_manager,
            )
            self._ws_manager.register_protocol(node_id=node_id, protocol=protocol)
            await protocol.run()

        except ClientCertError as e:
            self._log.error(f"WS remote_executor Auth failed: {e.detail}")
            await websocket.close(code=4003)
        except WebSocketDisconnect:
            self._ws_manager.unregister_protocol(node_id=node_id)
            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id, connected=False, via=None
            )
        except Exception as e:
            self._log.error(f"WS remote_executor unexpected error: {e}")
            self._ws_manager.unregister_protocol(node_id=node_id)
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

    async def logs_endpoint(self, websocket: WebSocket):
        await websocket.accept()
        user_id = None
        subscriptions = set()
        serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey, salt="ws-auth"
        )
        try:
            while True:
                data = await websocket.receive_text()
                msg = WsMessage.model_validate_json(data)

                if msg.msg_type == "authenticate":
                    try:
                        token_data = serializer.loads(msg.msg_body.token, max_age=5)
                        user_id = token_data.get("user_id")
                        self._log.info(f"WS logs authenticated user: {user_id}")
                    except (BadSignature, SignatureExpired) as e:
                        self._log.error(f"WS logs auth failed: {e}")
                        await websocket.close(code=4003)
                        return

                elif user_id:
                    if msg.msg_type == "subscribe_job_logs":
                        job_run_id = msg.msg_body.id
                        await self._ws_manager.subscribe(websocket, job_run_id)
                        subscriptions.add(job_run_id)
                    elif msg.msg_type == "unsubscribe_job_logs":
                        job_run_id = msg.msg_body.id
                        await self._ws_manager.unsubscribe(websocket, job_run_id)
                        subscriptions.discard(job_run_id)
                else:
                    self._log.warning("WS logs received message before authentication")
                    await websocket.close(code=4003)
                    return
        except WebSocketDisconnect:
            for job_run_id in subscriptions:
                await self._ws_manager.unsubscribe(websocket, job_run_id)
        except Exception as e:
            self._log.error(f"WS logs error: {e}")
            for job_run_id in subscriptions:
                await self._ws_manager.unsubscribe(websocket, job_run_id)
            await websocket.close(code=4003)

    async def inter_api_endpoint(self, websocket: WebSocket):
        client_host = websocket.client.host if websocket.client else "unknown"
        self._log.info(f"WS inter_api: connection attempt from {client_host}")
        try:
            await websocket.accept()
            self._log.info(f"WS inter_api: connection accepted from {client_host}")

            try:
                cn = await self._authorize_client_cert.require_cn(request=websocket)
                self._log.info(f"WS inter_api: client cert CN extracted: {cn}")
            except Exception as e:
                self._log.error(
                    f"WS inter_api: failed to extract CN from client cert: {e}"
                )
                await websocket.close(code=4003)
                return

            # Check if CN has a recently updated object in PyppetdbNodes
            try:
                node = await self._crud_pyppetdb_nodes.get(
                    _id=cn, fields=["id", "heartbeat"]
                )
                now = datetime.now()
                if (now - node.heartbeat).total_seconds() > 60:
                    self._log.error(
                        f"WS inter_api auth failed: heartbeat too old for {cn} (last: {node.heartbeat})"
                    )
                    await websocket.close(code=4003)
                    return
            except Exception as e:
                self._log.error(f"WS inter_api auth failed for {cn}: {e}")
                await websocket.close(code=4003)
                return

            self._log.info(f"WS inter_api authenticated server: {cn}")
            subscriptions = set()

            while True:
                data = await websocket.receive_text()
                self._log.debug(f"WS inter_api received message from {cn}: {data}")
                msg = WsMessage.model_validate_json(data)

                if msg.msg_type == "subscribe_job_logs":
                    job_run_id = msg.msg_body.id
                    self._log.info(
                        f"WS inter_api: {cn} subscribing to logs for {job_run_id}"
                    )
                    await self._ws_manager.subscribe(websocket, job_run_id)
                    subscriptions.add(job_run_id)
                elif msg.msg_type == "unsubscribe_job_logs":
                    job_run_id = msg.msg_body.id
                    self._log.info(
                        f"WS inter_api: {cn} unsubscribing from logs for {job_run_id}"
                    )
                    await self._ws_manager.unsubscribe(websocket, job_run_id)
                    subscriptions.discard(job_run_id)

        except WebSocketDisconnect:
            self._log.info(
                f"WS inter_api: connection disconnected from {cn if 'cn' in locals() else client_host}"
            )
            for job_run_id in subscriptions:
                await self._ws_manager.unsubscribe(websocket, job_run_id)
        except Exception as e:
            self._log.error(f"WS inter_api error: {e}")
            if "subscriptions" in locals():
                for job_run_id in subscriptions:
                    await self._ws_manager.unsubscribe(websocket, job_run_id)
            await websocket.close(code=4003)
