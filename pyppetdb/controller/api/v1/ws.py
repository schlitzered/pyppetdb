import logging
import socket
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pyppetdb.authorize import AuthorizePyppetDB, AuthorizeClientCert
from pyppetdb.errors import ClientCertError
from pyppetdb.crud.nodes import CrudNodes

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
        authorize: AuthorizePyppetDB,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes: CrudNodes,
    ):
        self._authorize = authorize
        self._authorize_client_cert = authorize_client_cert
        self._crud_nodes = crud_nodes
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

            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
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
