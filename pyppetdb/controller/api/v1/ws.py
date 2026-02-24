import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse

from pyppetdb.authorize import AuthorizePyppetDB

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
    </head>
    <body>
        <h1>WebSocket Chat</h1>
        <h2>Your ID: <span id="ws-id"></span></h2>
        <form action="" onsubmit="sendMessage(event)">
            <input type="text" id="messageText" autocomplete="off"/>
            <button>Send</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var client_id = Date.now()
            document.querySelector("#ws-id").textContent = client_id;
            var ws = new WebSocket(`ws://localhost:8000/api/v1/ws/ws/${client_id}`);
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                var content = document.createTextNode(event.data)
                message.appendChild(content)
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
    ):
        self._authorize = authorize
        self._conns = ConnectionManager()
        self._log = log
        self._router = APIRouter(
            prefix="/ws",
            tags=["websocket"],
        )
        self.router.add_api_route(
            "/",
            self.get,
            methods=["GET"],
        )
        self.router.add_api_websocket_route(
            "/ws/{client_id}",
            self.websocket_endpoint,
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def conns(self):
        return self._conns

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    @staticmethod
    def get():
        return HTMLResponse(html)

    async def websocket_endpoint(self, websocket: WebSocket, client_id: int):
        self.log.info(websocket.headers)
        self.log.info(websocket.cookies)
        await self.conns.connect(websocket)
        self.log.info(websocket.headers)
        self.log.info(websocket.cookies)
        #        await self.authorize.require_user(request=websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await self.conns.send_personal_message(f"You wrote: {data}", websocket)
                await self.conns.broadcast(f"Client #{client_id} says: {data}")
        except WebSocketDisconnect:
            self.conns.disconnect(websocket)
            await self.conns.broadcast(f"{websocket.client} left the chat")
