import asyncio
import logging
import json
import ssl
from datetime import datetime
from typing import Dict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
import websockets

from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.model.ws import WsMessage
from pyppetdb.model.ws import WsMsgBodyJobLogs
from pyppetdb.model.ws import WsMsgBodyApiGetLogChunks
from pyppetdb.model.ws import WsMsgBodyApiGetLogChunk
from pyppetdb.model.ws import WsMsgBodyApiLogChunksResponse
from pyppetdb.model.ws import WsMsgBodyApiLogChunkResponse


class WsInterAPI:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        hub: Any,
        authorize_client_cert: AuthorizeClientCert,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
    ):
        self._log = log
        self._config = config
        self._hub = hub
        self._authorize_client_cert = authorize_client_cert
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes

        self._remote_conns: Dict[str, Any] = {}
        self._remote_locks: Dict[str, asyncio.Lock] = {}
        self._pending_requests: Dict[str, asyncio.Future] = {}

    async def endpoint(self, websocket: WebSocket):
        cn = "unknown"
        try:
            await websocket.accept()
            try:
                cn = await self._authorize_client_cert.require_cn(request=websocket)
            except Exception as e:
                self._log.error(msg=f"WS inter_api: auth failed: {e}")
                await websocket.close(code=4003)
                return

            if not await self._authenticate(cn):
                await websocket.close(code=4003)
                return

            self._log.info(msg=f"WS inter_api: accepted connection from {cn}")

            subscriptions = set()
            try:
                while True:
                    data = await websocket.receive_text()
                    await self._handle_server_message(
                        websocket=websocket,
                        data=data,
                        subscriptions=subscriptions,
                    )
            except WebSocketDisconnect:
                pass
            finally:
                self._log.info(msg=f"WS inter_api: connection from {cn} closed")
                for job_run_id in list(subscriptions):
                    await self._hub.unsubscribe(
                        websocket=websocket,
                        job_run_id=job_run_id,
                    )

        except Exception as e:
            self._log.error(msg=f"WS inter_api error: {e}")
            await websocket.close(code=4003)

    async def _authenticate(self, cn: str) -> bool:
        try:
            node = await self._crud_pyppetdb_nodes.get(
                _id=cn,
                fields=["id", "heartbeat"],
            )
            now = datetime.now()
            return (now - node.heartbeat).total_seconds() <= 60
        except Exception:
            return False

    async def _handle_server_message(
        self,
        websocket: WebSocket,
        data: str,
        subscriptions: set,
    ):
        msg = WsMessage.model_validate_json(json_data=data)

        if msg.msg_type == "subscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self._hub.subscribe(websocket, job_run_id)
            subscriptions.add(job_run_id)
        elif msg.msg_type == "unsubscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self._hub.unsubscribe(websocket, job_run_id)
            subscriptions.discard(job_run_id)
        elif msg.msg_type == "api_get_log_chunks":
            await self._handle_get_log_chunks(websocket, msg.msg_body)
        elif msg.msg_type == "api_get_log_chunk":
            await self._handle_get_log_chunk(websocket, msg.msg_body)

    async def _handle_get_log_chunks(self, websocket, msg_body):
        job_run_id = msg_body.job_run_id
        request_id = msg_body.request_id
        chunks = await self._hub.get_log_chunks(job_run_id=job_run_id)
        resp = WsMessage(
            msg_type="api_log_chunks_response",
            msg_body=WsMsgBodyApiLogChunksResponse(
                job_run_id=job_run_id,
                request_id=request_id,
                chunks=chunks,
            ),
        )
        await websocket.send_text(data=resp.model_dump_json())

    async def _handle_get_log_chunk(self, websocket, msg_body):
        job_run_id = msg_body.job_run_id
        request_id = msg_body.request_id
        chunk_id = msg_body.chunk_id
        data = await self._hub.get_log_chunk(
            job_run_id=job_run_id,
            chunk_id=chunk_id,
        )
        resp = WsMessage(
            msg_type="api_log_chunk_response",
            msg_body=WsMsgBodyApiLogChunkResponse(
                job_run_id=job_run_id,
                request_id=request_id,
                chunk_id=chunk_id,
                data=data if data is not None else [],
                status=200 if data is not None else 404,
            ),
        )
        await websocket.send_text(data=resp.model_dump_json())

    async def get_log_chunks(
        self,
        via: str,
        job_run_id: str,
        request_id: str,
        future: asyncio.Future,
    ):
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if not ws:
            future.set_result([])
            return

        self._pending_requests[request_id] = future
        msg = WsMessage(
            msg_type="api_get_log_chunks",
            msg_body=WsMsgBodyApiGetLogChunks(
                job_run_id=job_run_id,
                request_id=request_id,
            ),
        )
        await ws.send(msg.model_dump_json())

    async def get_log_chunk(
        self,
        via: str,
        job_run_id: str,
        chunk_id: str,
        request_id: str,
        future: asyncio.Future,
    ):
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if not ws:
            future.set_result(None)
            return

        self._pending_requests[request_id] = future
        msg = WsMessage(
            msg_type="api_get_log_chunk",
            msg_body=WsMsgBodyApiGetLogChunk(
                job_run_id=job_run_id,
                chunk_id=chunk_id,
                request_id=request_id,
            ),
        )
        await ws.send(msg.model_dump_json())

    async def subscribe(self, via: str, job_run_id: str):
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if ws:
            sub_msg = WsMessage(
                msg_type="subscribe_job_logs",
                msg_body=WsMsgBodyJobLogs(id=job_run_id),
            )
            try:
                await ws.send(sub_msg.model_dump_json())
            except Exception as e:
                self._log.error(
                    msg=f"Failed to send subscription for {job_run_id} to {via}: {e}"
                )

    async def unsubscribe(self, via: str, job_run_id: str):
        ws = self._remote_conns.get(via)
        if ws:
            unsub_msg = WsMessage(
                msg_type="unsubscribe_job_logs",
                msg_body=WsMsgBodyJobLogs(id=job_run_id),
            )
            try:
                await ws.send(unsub_msg.model_dump_json())
            except Exception as e:
                self._log.error(msg=f"Failed to send unsubscription to {via}: {e}")

    async def _ensure_remote_connection(self, via: str):
        if via not in self._remote_locks:
            self._remote_locks[via] = asyncio.Lock()

        async with self._remote_locks[via]:
            if via not in self._remote_conns:
                asyncio.create_task(coro=self._remote_api_client(via=via))
                for _ in range(20):
                    if via in self._remote_conns:
                        break
                    await asyncio.sleep(delay=0.1)

    async def _remote_api_client(self, via: str):
        port = self._config.app.main.port
        ssl_cert = self._config.app.main.ssl.cert if self._config.app.main.ssl else None
        ssl_key = self._config.app.main.ssl.key if self._config.app.main.ssl else None
        ssl_ca = self._config.app.main.ssl.ca if self._config.app.main.ssl else None

        if not ssl_cert or not ssl_key:
            return

        url = f"wss://{via}:{port}/api/v1/ws/inter_api/"
        ssl_context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH, cafile=ssl_ca
        )
        ssl_context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)

        last_activity = asyncio.get_event_loop().time()

        while True:
            try:
                async with websockets.connect(uri=url, ssl=ssl_context) as ws:
                    self._log.info(msg=f"Initiating Inter-API connection to {via}")
                    self._remote_conns[via] = ws

                    for jrid, jvia in self._hub.job_run_id_to_via.items():
                        if jvia == via:
                            sub_msg = WsMessage(
                                msg_type="subscribe_job_logs",
                                msg_body=WsMsgBodyJobLogs(id=jrid),
                            )
                            await ws.send(sub_msg.model_dump_json())

                    try:
                        while True:
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                                last_activity = await self._handle_remote_api_message(
                                    via, message
                                )
                            except asyncio.TimeoutError:
                                has_subscriptions = any(
                                    v == via
                                    for v in self._hub.job_run_id_to_via.values()
                                )
                                if not has_subscriptions and (
                                    asyncio.get_event_loop().time() - last_activity
                                    > self._config.app.main.interApiIdleTimeout
                                ):
                                    self._log.info(
                                        msg=f"Closing idle Inter-API connection to {via} due to inactivity"
                                    )
                                    await ws.close()
                                    return
                    finally:
                        self._log.info(msg=f"Inter-API connection to {via} closed")
                        self._remote_conns.pop(via, None)
            except Exception as e:
                self._log.error(msg=f"Inter-API connection to {via} failed: {e}")
                self._remote_conns.pop(via, None)

            has_subscriptions = any(
                v == via for v in self._hub.job_run_id_to_via.values()
            )
            if not has_subscriptions and (
                asyncio.get_event_loop().time() - last_activity
                > self._config.app.main.interApiIdleTimeout
            ):
                self._log.info(
                    msg=f"Closing idle Inter-API connection to {via} due to inactivity"
                )
                break
            await asyncio.sleep(delay=5)

    async def _handle_remote_api_message(self, via: str, message: str) -> float:
        data = json.loads(s=message)
        msg_type = data.get("msg_type")
        msg_body = data.get("msg_body")
        if not msg_body:
            return asyncio.get_event_loop().time()

        request_id = msg_body.get("request_id")
        if request_id and request_id in self._pending_requests:
            self._handle_remote_api_response(msg_type, msg_body, request_id)
            return asyncio.get_event_loop().time()

        job_run_id = msg_body.get("job_run_id") or msg_body.get("id")
        if not job_run_id:
            return asyncio.get_event_loop().time()

        if job_run_id in self._hub.subscriptions:
            await self._hub.broadcast_remote_message(job_run_id, message)

        return asyncio.get_event_loop().time()

    def _handle_remote_api_response(self, msg_type, msg_body, request_id):
        if msg_type == "api_log_chunks_response":
            self._pending_requests[request_id].set_result(msg_body.get("chunks"))
        elif msg_type == "api_log_chunk_response":
            self._pending_requests[request_id].set_result(msg_body.get("data"))
        self._pending_requests.pop(request_id, None)
