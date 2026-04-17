import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.ws.manager import WsManager
from pyppetdb.model.ws import WsMessage
from pyppetdb.model.ws import WsMsgBodyApiLogChunksResponse
from pyppetdb.model.ws import WsMsgBodyApiLogChunkResponse


class WsInterAPI:
    def __init__(
        self,
        log: logging.Logger,
        authorize_client_cert: AuthorizeClientCert,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        ws_manager: WsManager,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._ws_manager = ws_manager

    async def endpoint(
        self,
        websocket: WebSocket,
    ):
        client_host = websocket.client.host if websocket.client else "unknown"
        self._log.info(msg=f"WS inter_api: connection attempt from {client_host}")
        cn = "unknown"
        try:
            await websocket.accept()
            self._log.info(msg=f"WS inter_api: connection accepted from {client_host}")

            try:
                cn = await self._authorize_client_cert.require_cn(request=websocket)
                self._log.info(msg=f"WS inter_api: client cert CN extracted: {cn}")
            except Exception as e:
                self._log.error(
                    msg=f"WS inter_api: failed to extract CN from client cert: {e}"
                )
                await websocket.close(code=4003)
                return

            if not await self._authenticate(cn, websocket):
                return

            self._log.info(msg=f"WS inter_api authenticated server: {cn}")
            subscriptions = set()

            try:
                while True:
                    data = await websocket.receive_text()
                    await self._handle_message(
                        cn=cn,
                        websocket=websocket,
                        data=data,
                        subscriptions=subscriptions,
                    )
            except WebSocketDisconnect:
                self._log.info(msg=f"WS inter_api: connection disconnected from {cn}")
            finally:
                for job_run_id in list(subscriptions):
                    await self._ws_manager.unsubscribe(
                        websocket=websocket,
                        job_run_id=job_run_id,
                    )

        except Exception as e:
            self._log.error(msg=f"WS inter_api error: {e}")
            await websocket.close(code=4003)

    async def _authenticate(self, cn: str, websocket: WebSocket) -> bool:
        try:
            node = await self._crud_pyppetdb_nodes.get(
                _id=cn,
                fields=["id", "heartbeat"],
            )
            now = datetime.now()
            if (now - node.heartbeat).total_seconds() > 60:
                self._log.error(
                    msg=f"WS inter_api auth failed: heartbeat too old for {cn} (last: {node.heartbeat})"
                )
                await websocket.close(code=4003)
                return False
            return True
        except Exception as e:
            self._log.error(msg=f"WS inter_api auth failed for {cn}: {e}")
            await websocket.close(code=4003)
            return False

    async def _handle_message(
        self,
        cn: str,
        websocket: WebSocket,
        data: str,
        subscriptions: set,
    ):
        self._log.debug(msg=f"WS inter_api received message from {cn}: {data}")
        msg = WsMessage.model_validate_json(json_data=data)

        if msg.msg_type == "subscribe_job_logs":
            await self._handle_subscribe(websocket, msg.msg_body.id, cn, subscriptions)
        elif msg.msg_type == "unsubscribe_job_logs":
            await self._handle_unsubscribe(
                websocket, msg.msg_body.id, cn, subscriptions
            )
        elif msg.msg_type == "api_get_log_chunks":
            await self._handle_get_log_chunks(websocket, msg.msg_body, cn)
        elif msg.msg_type == "api_get_log_chunk":
            await self._handle_get_log_chunk(websocket, msg.msg_body, cn)

    async def _handle_subscribe(self, websocket, job_run_id, cn, subscriptions):
        self._log.info(msg=f"WS inter_api: {cn} subscribing to logs for {job_run_id}")
        await self._ws_manager.subscribe(
            websocket=websocket,
            job_run_id=job_run_id,
        )
        subscriptions.add(job_run_id)

    async def _handle_unsubscribe(self, websocket, job_run_id, cn, subscriptions):
        self._log.info(
            msg=f"WS inter_api: {cn} unsubscribing from logs for {job_run_id}"
        )
        await self._ws_manager.unsubscribe(
            websocket=websocket,
            job_run_id=job_run_id,
        )
        subscriptions.discard(job_run_id)

        # Also tell the local agent to stop streaming if this was the last subscriber
        try:
            job_id, node_id = job_run_id.split(":", 1)
            protocol = self._ws_manager._local_protocols.get(node_id)
            if protocol:
                from pyppetdb.model.remote_executor import (
                    RemoteExecutorMsgBodyUnsubscribeLogs,
                )

                await protocol._send_message(
                    msg_type="unsubscribe_logs",
                    body=RemoteExecutorMsgBodyUnsubscribeLogs(job_id=job_id),
                )
        except Exception as e:
            self._log.error(
                msg=f"Error sending inter-API unsubscribe to local agent: {e}"
            )

    async def _handle_get_log_chunks(self, websocket, msg_body, cn):
        job_run_id = msg_body.job_run_id
        request_id = msg_body.request_id
        self._log.info(msg=f"WS inter_api: {cn} requesting log chunks for {job_run_id}")
        chunks = await self._ws_manager.get_log_chunks(
            job_run_id=job_run_id,
        )
        resp = WsMessage(
            msg_type="api_log_chunks_response",
            msg_body=WsMsgBodyApiLogChunksResponse(
                job_run_id=job_run_id,
                request_id=request_id,
                chunks=chunks,
            ),
        )
        await websocket.send_text(data=resp.model_dump_json())

    async def _handle_get_log_chunk(self, websocket, msg_body, cn):
        job_run_id = msg_body.job_run_id
        request_id = msg_body.request_id
        chunk_id = msg_body.chunk_id
        self._log.info(
            msg=f"WS inter_api: {cn} requesting log chunk {chunk_id} for {job_run_id}"
        )
        data = await self._ws_manager.get_log_chunk(
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
