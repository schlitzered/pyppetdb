import asyncio
import logging
import json
import socket
import uuid
from typing import Dict
from typing import Set
from typing import Optional
from typing import Any
from typing import List

from fastapi import WebSocket

from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.model.ws import WsMessage
from pyppetdb.model.ws import WsMsgBodyLogMessage
from pyppetdb.model.ws import WsMsgBodyJobFinished
from pyppetdb.model.ws import WsMsgBodyJobLogs
from pyppetdb.model.ws import WsMsgBodyApiGetLogChunks
from pyppetdb.model.ws import WsMsgBodyApiGetLogChunk


class WsManager:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_node_jobs: CrudJobsNodeJobs,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
    ):
        self._log = log
        self._config = config
        self._crud_nodes = crud_nodes
        self._crud_node_jobs = crud_node_jobs
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._via = socket.getfqdn()

        self._subscriptions: Dict[str, Set[WebSocket]] = {}
        self._local_protocols: Dict[str, Any] = {}
        self._remote_conns: Dict[str, Any] = {}
        self._remote_locks: Dict[str, asyncio.Lock] = {}
        self._job_run_id_to_via: Dict[str, str] = {}

        self._pending_requests: Dict[str, asyncio.Future] = {}

    def register_protocol(
        self,
        node_id: str,
        protocol: Any,
    ):
        old_protocol = self._local_protocols.get(node_id)
        if old_protocol:
            self._log.info(msg=f"Stopping existing protocol for node {node_id}")
            old_protocol.stop()
        self._local_protocols[node_id] = protocol

    def unregister_protocol(
        self,
        node_id: str,
    ):
        self._local_protocols.pop(
            node_id,
            None,
        )

    async def broadcast_local_log(
        self,
        node_id: str,
        job_id: str,
        log_entry: Dict,
    ):
        job_run_id = f"{job_id}:{node_id}"
        if job_run_id in self._subscriptions:
            msg = WsMessage(
                msg_type="log_message",
                msg_body=WsMsgBodyLogMessage(
                    job_run_id=job_run_id,
                    logs=[log_entry],
                ),
            )
            await self._broadcast_to_subscribers(job_run_id, msg.model_dump_json())

    async def _broadcast_to_subscribers(self, job_run_id: str, data: str):
        for ws in list(self._subscriptions.get(job_run_id, [])):
            try:
                await ws.send_text(data=data)
            except Exception:
                self._subscriptions[job_run_id].remove(ws)

    async def job_finished(
        self,
        node_id: str,
        job_id: str,
        status: str,
        exit_code: Optional[int] = None,
    ):
        job_run_id = f"{job_id}:{node_id}"
        if job_run_id in self._subscriptions:
            msg = WsMessage(
                msg_type="job_finished",
                msg_body=WsMsgBodyJobFinished(
                    job_run_id=job_run_id,
                    status=status,
                    exit_code=exit_code,
                ),
            )
            await self._broadcast_to_subscribers(job_run_id, msg.model_dump_json())

    async def subscribe(
        self,
        websocket: WebSocket,
        job_run_id: str,
    ):
        is_first = False
        if job_run_id not in self._subscriptions:
            self._subscriptions[job_run_id] = set()
            is_first = True

        self._subscriptions[job_run_id].add(websocket)

        if not is_first:
            return

        try:
            await self._handle_first_subscription(job_run_id)
        except Exception as e:
            self._log.error(msg=f"Error determining local/remote for {job_run_id}: {e}")

    async def _handle_first_subscription(self, job_run_id: str):
        job_id, node_id = job_run_id.split(":", 1)
        node = await self._crud_nodes.get(
            _id=node_id,
            fields=["remote_agent"],
        )
        if node.remote_agent and node.remote_agent.connected:
            if node.remote_agent.via != self._via:
                self._job_run_id_to_via[job_run_id] = node.remote_agent.via
                await self._ensure_remote_subscription(
                    job_run_id=job_run_id,
                    via=node.remote_agent.via,
                )
            else:
                await self._subscribe_local_agent(node_id, job_id)

    async def _subscribe_local_agent(self, node_id: str, job_id: str):
        protocol = self._local_protocols.get(node_id)
        if protocol:
            from pyppetdb.model.remote_executor import (
                RemoteExecutorMsgBodySubscribeLogs,
            )

            await protocol._send_message(
                msg_type="subscribe_logs",
                body=RemoteExecutorMsgBodySubscribeLogs(job_id=job_id),
            )

    async def unsubscribe(
        self,
        websocket: WebSocket,
        job_run_id: str,
    ):
        if job_run_id in self._subscriptions:
            self._subscriptions[job_run_id].discard(websocket)
            if not self._subscriptions[job_run_id]:
                await self._handle_last_unsubscription(job_run_id)

    async def _handle_last_unsubscription(self, job_run_id: str):
        del self._subscriptions[job_run_id]
        via = self._job_run_id_to_via.pop(
            job_run_id,
            None,
        )
        if via:
            await self._remote_unsubscribe(
                job_run_id=job_run_id,
                via=via,
            )
        else:
            await self._unsubscribe_local_agent(job_run_id)

    async def _unsubscribe_local_agent(self, job_run_id: str):
        try:
            job_id, node_id = job_run_id.split(":", 1)
            protocol = self._local_protocols.get(node_id)
            if protocol:
                from pyppetdb.model.remote_executor import (
                    RemoteExecutorMsgBodyUnsubscribeLogs,
                )

                await protocol._send_message(
                    msg_type="unsubscribe_logs",
                    body=RemoteExecutorMsgBodyUnsubscribeLogs(job_id=job_id),
                )
        except Exception as e:
            self._log.error(msg=f"Error sending unsubscribe_logs to local agent: {e}")

    async def _remote_unsubscribe(
        self,
        job_run_id: str,
        via: str,
    ):
        ws = self._remote_conns.get(via)
        if ws:
            unsub_msg = WsMessage(
                msg_type="unsubscribe_job_logs",
                msg_body=WsMsgBodyJobLogs(id=job_run_id),
            )
            try:
                self._log.info(msg=f"Sending unsubscription for {job_run_id} to {via}")
                await ws.send(unsub_msg.model_dump_json())
            except Exception as e:
                self._log.error(msg=f"Failed to send unsubscription to {via}: {e}")

    async def _ensure_remote_subscription(
        self,
        job_run_id: str,
        via: str,
    ):
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if ws:
            sub_msg = WsMessage(
                msg_type="subscribe_job_logs",
                msg_body=WsMsgBodyJobLogs(id=job_run_id),
            )
            self._log.info(msg=f"Sending subscription for {job_run_id} to {via}")
            try:
                await ws.send(sub_msg.model_dump_json())
            except Exception as e:
                self._log.error(
                    msg=f"Failed to send subscription for {job_run_id} to {via}: {e}"
                )

    async def _ensure_remote_connection(
        self,
        via: str,
    ):
        if via not in self._remote_locks:
            self._remote_locks[via] = asyncio.Lock()

        async with self._remote_locks[via]:
            if via not in self._remote_conns:
                asyncio.create_task(coro=self._remote_api_client(via=via))
                for _ in range(20):
                    if via in self._remote_conns:
                        break
                    await asyncio.sleep(delay=0.1)

    async def get_log_chunks(
        self,
        job_run_id: str,
    ) -> List[str]:
        try:
            job_id, node_id = job_run_id.split(":", 1)
            node = await self._crud_nodes.get(
                _id=node_id,
                fields=["remote_agent"],
            )
            if not node.remote_agent or not node.remote_agent.connected:
                return []

            request_id = str(uuid.uuid4())
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future

            if node.remote_agent.via == self._via:
                await self._request_log_chunks_local(
                    node_id, job_id, request_id, future
                )
            else:
                await self._request_log_chunks_remote(
                    node.remote_agent.via, job_run_id, request_id
                )

            try:
                return await asyncio.wait_for(fut=future, timeout=20)
            except asyncio.TimeoutError:
                self._log.warning(
                    msg=f"Timeout waiting for log chunks for {job_run_id}"
                )
                return []
            finally:
                self._cleanup_pending_request(
                    request_id, node_id if node.remote_agent.via == self._via else None
                )

        except Exception as e:
            self._log.error(msg=f"Error getting log chunks for {job_run_id}: {e}")
            return []

    async def _request_log_chunks_local(self, node_id, job_id, request_id, future):
        protocol = self._local_protocols.get(node_id)
        if not protocol:
            future.set_result([])
            return
        protocol._pending_agent_requests[request_id] = future
        await protocol.request_log_chunks(job_id=job_id, request_id=request_id)

    async def _request_log_chunks_remote(self, via, job_run_id, request_id):
        self._log.info(msg=f"Forwarding log chunks request for {job_run_id} to {via}")
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if not ws:
            self._log.error(msg=f"Failed to get inter-API connection to {via}")
            if request_id in self._pending_requests:
                self._pending_requests[request_id].set_result([])
            return
        msg = WsMessage(
            msg_type="api_get_log_chunks",
            msg_body=WsMsgBodyApiGetLogChunks(
                job_run_id=job_run_id, request_id=request_id
            ),
        )
        await ws.send(msg.model_dump_json())

    def _cleanup_pending_request(
        self, request_id: str, local_node_id: Optional[str] = None
    ):
        self._pending_requests.pop(request_id, None)
        if local_node_id:
            protocol = self._local_protocols.get(local_node_id)
            if protocol:
                protocol._pending_agent_requests.pop(request_id, None)

    async def get_log_chunk(
        self,
        job_run_id: str,
        chunk_id: str,
    ) -> Optional[List[Dict]]:
        try:
            job_id, node_id = job_run_id.split(":", 1)
            node = await self._crud_nodes.get(
                _id=node_id,
                fields=["remote_agent"],
            )
            if not node.remote_agent or not node.remote_agent.connected:
                return None

            request_id = str(uuid.uuid4())
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future

            if node.remote_agent.via == self._via:
                await self._request_log_chunk_local(
                    node_id, job_id, chunk_id, request_id, future
                )
            else:
                await self._request_log_chunk_remote(
                    node.remote_agent.via, job_run_id, chunk_id, request_id
                )

            try:
                return await asyncio.wait_for(fut=future, timeout=20)
            except asyncio.TimeoutError:
                self._log.warning(msg=f"Timeout waiting for log chunk for {job_run_id}")
                return None
            finally:
                self._cleanup_pending_request(
                    request_id, node_id if node.remote_agent.via == self._via else None
                )

        except Exception as e:
            self._log.error(msg=f"Error getting log chunk for {job_run_id}: {e}")
            return None

    async def _request_log_chunk_local(
        self, node_id, job_id, chunk_id, request_id, future
    ):
        protocol = self._local_protocols.get(node_id)
        if not protocol:
            future.set_result(None)
            return
        protocol._pending_agent_requests[request_id] = future
        await protocol.request_log_chunk(
            job_id=job_id, chunk_id=chunk_id, request_id=request_id
        )

    async def _request_log_chunk_remote(self, via, job_run_id, chunk_id, request_id):
        await self._ensure_remote_connection(via=via)
        ws = self._remote_conns.get(via)
        if not ws:
            if request_id in self._pending_requests:
                self._pending_requests[request_id].set_result(None)
            return
        msg = WsMessage(
            msg_type="api_get_log_chunk",
            msg_body=WsMsgBodyApiGetLogChunk(
                job_run_id=job_run_id, chunk_id=chunk_id, request_id=request_id
            ),
        )
        await ws.send(msg.model_dump_json())

    async def _remote_api_client(
        self,
        via: str,
    ):
        port = self._config.app.main.port
        ssl_cert = self._config.app.main.ssl.cert if self._config.app.main.ssl else None
        ssl_key = self._config.app.main.ssl.key if self._config.app.main.ssl else None
        ssl_ca = self._config.app.main.ssl.ca if self._config.app.main.ssl else None

        scheme = "wss" if ssl_cert and ssl_key else "ws"
        url = f"{scheme}://{via}:{port}/api/v1/ws/inter_api/"

        import websockets
        import ssl

        ssl_context = None
        if scheme == "wss":
            ssl_context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH, cafile=ssl_ca
            )
            ssl_context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)

        last_activity = asyncio.get_event_loop().time()

        while True:
            self._log.info(msg=f"Establishing inter-API connection to {via} at {url}")
            try:
                async with websockets.connect(uri=url, ssl=ssl_context) as ws:
                    self._log.info(msg=f"Inter-API connection to {via} established")
                    self._remote_conns[via] = ws

                    for jrid, jvia in self._job_run_id_to_via.items():
                        if jvia == via:
                            sub_msg = WsMessage(
                                msg_type="subscribe_job_logs",
                                msg_body=WsMsgBodyJobLogs(id=jrid),
                            )
                            await ws.send(sub_msg.model_dump_json())

                    try:
                        async for message in ws:
                            last_activity = await self._handle_remote_api_message(
                                via, message
                            )
                    finally:
                        self._log.info(msg=f"Inter-API connection to {via} closed")
                        self._remote_conns.pop(via, None)
            except Exception as e:
                self._log.error(msg=f"Inter-API connection to {via} failed: {e}")
                self._remote_conns.pop(via, None)

            has_subscriptions = any(v == via for v in self._job_run_id_to_via.values())
            if not has_subscriptions and (
                asyncio.get_event_loop().time() - last_activity > 300.0
            ):
                self._log.info(
                    msg=f"No more subscriptions for {via} and idle, stopping inter-API client"
                )
                break

            await asyncio.sleep(delay=5)

    async def _handle_remote_api_message(self, via: str, message: str) -> float:
        self._log.debug(msg=f"Inter-API received message from {via}: {message}")
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

        if job_run_id in self._subscriptions:
            self._log.debug(msg=f"Inter-API broadcasting log message for {job_run_id}")
            await self._broadcast_to_subscribers(job_run_id, message)

        return asyncio.get_event_loop().time()

    def _handle_remote_api_response(self, msg_type, msg_body, request_id):
        self._log.debug(msg=f"Inter-API found pending request for {request_id}")
        if msg_type == "api_log_chunks_response":
            self._pending_requests[request_id].set_result(msg_body.get("chunks"))
        elif msg_type == "api_log_chunk_response":
            self._pending_requests[request_id].set_result(msg_body.get("data"))
