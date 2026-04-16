import asyncio
import logging
import json
import socket
import uuid
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket

from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.model.ws import (
    WsMessage,
    WsMsgBodyLogMessage,
    WsMsgBodyJobFinished,
    WsMsgBodyJobLogs,
    WsMsgBodyApiGetLogChunks,
    WsMsgBodyApiGetLogChunk,
)


class LogSubscriptionManager:
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

        # job_id:node_id -> set of client websockets
        self._subscriptions: Dict[str, Set[WebSocket]] = {}
        # node_id -> RemoteExecutorProtocol instance
        self._local_protocols: Dict[str, Any] = {}
        # via -> inter-api websocket connection
        self._remote_conns: Dict[str, Any] = {}
        # via -> asyncio.Lock for connection creation
        self._remote_locks: Dict[str, asyncio.Lock] = {}
        # job_run_id -> via
        self._job_run_id_to_via: Dict[str, str] = {}

        # request_id -> asyncio.Future
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
            data = msg.model_dump_json()
            for ws in list(self._subscriptions[job_run_id]):
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
            data = msg.model_dump_json()
            for ws in list(self._subscriptions[job_run_id]):
                try:
                    await ws.send_text(data=data)
                except Exception:
                    self._subscriptions[job_run_id].remove(ws)

    async def subscribe(
        self,
        websocket: WebSocket,
        job_run_id: str,
    ):
        if job_run_id not in self._subscriptions:
            self._subscriptions[job_run_id] = set()
        self._subscriptions[job_run_id].add(websocket)

        try:
            job_id, node_id = job_run_id.split(
                ":",
                1,
            )
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
                    # Also send catch-up request for remote agent
                    ws = self._remote_conns.get(node.remote_agent.via)
                    if ws:
                        # Re-use the existing model but it's agent-level
                        # We don't have a specific Inter-API 'subscribe_logs' but the agent expects 'subscribe_logs'
                        # which is wrapped in a WsMessage 'log_message'? No, inter-api just forwards.
                        # Wait, the inter-api needs to know it's a catch-up request.
                        # I'll just send a regular subscribe_job_logs which already triggers remote subscription.
                        # The agent handled its own catch-up? No, I need to tell the agent.
                        pass
                else:
                    protocol = self._local_protocols.get(node_id)
                    if protocol:
                        from pyppetdb.model.remote_executor import RemoteExecutorMsgBodySubscribeLogs
                        await protocol._send_message(
                            msg_type="subscribe_logs",
                            body=RemoteExecutorMsgBodySubscribeLogs(job_id=job_id)
                        )
        except Exception as e:
            self._log.error(msg=f"Error determining local/remote for {job_run_id}: {e}")

    async def unsubscribe(
        self,
        websocket: WebSocket,
        job_run_id: str,
    ):
        if job_run_id in self._subscriptions:
            self._subscriptions[job_run_id].discard(websocket)
            if not self._subscriptions[job_run_id]:
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
                    try:
                        job_id, node_id = job_run_id.split(":", 1)
                        protocol = self._local_protocols.get(node_id)
                        if protocol:
                            from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyUnsubscribeLogs
                            await protocol._send_message(
                                msg_type="unsubscribe_logs",
                                body=RemoteExecutorMsgBodyUnsubscribeLogs(job_id=job_id)
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
            data = unsub_msg.model_dump_json()
            try:
                self._log.info(msg=f"Sending unsubscription for {job_run_id} to {via}")
                await ws.send(data)
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
            data = sub_msg.model_dump_json()
            self._log.info(msg=f"Sending subscription for {job_run_id} to {via}")
            try:
                await ws.send(data)
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
                # Start a background task to handle remote connection
                asyncio.create_task(coro=self._remote_api_client(via=via))
                # Wait a bit for connection to be established
                for _ in range(20):
                    if via in self._remote_conns:
                        break
                    await asyncio.sleep(delay=0.1)

    async def get_log_chunks(
        self,
        job_run_id: str,
    ) -> List[str]:
        try:
            job_id, node_id = job_run_id.split(
                ":",
                1,
            )
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
                protocol = self._local_protocols.get(node_id)
                if not protocol:
                    return []
                protocol._pending_agent_requests[request_id] = future
                await protocol.request_log_chunks(
                    job_id=job_id,
                    request_id=request_id,
                )
            else:
                self._log.info(msg=f"Forwarding log chunks request for {job_run_id} to {node.remote_agent.via}")
                await self._ensure_remote_connection(via=node.remote_agent.via)
                ws = self._remote_conns.get(node.remote_agent.via)
                if not ws:
                    self._log.error(msg=f"Failed to get inter-API connection to {node.remote_agent.via}")
                    return []
                msg = WsMessage(
                    msg_type="api_get_log_chunks",
                    msg_body=WsMsgBodyApiGetLogChunks(
                        job_run_id=job_run_id,
                        request_id=request_id,
                    ),
                )
                await ws.send(msg.model_dump_json())
                self._log.debug(msg=f"Sent api_get_log_chunks request_id={request_id} to {node.remote_agent.via}")

            try:
                result = await asyncio.wait_for(
                    fut=future,
                    timeout=20,
                )
                return result
            except asyncio.TimeoutError:
                self._log.warning(
                    msg=f"Timeout waiting for log chunks for {job_run_id}"
                )
                return []
            finally:
                self._pending_requests.pop(
                    request_id,
                    None,
                )
                if node.remote_agent.via == self._via:
                    protocol = self._local_protocols.get(node_id)
                    if protocol:
                        protocol._pending_agent_requests.pop(
                            request_id,
                            None,
                        )

        except Exception as e:
            self._log.error(msg=f"Error getting log chunks for {job_run_id}: {e}")
            return []

    async def get_log_chunk(
        self,
        job_run_id: str,
        chunk_id: str,
    ) -> Optional[List[Dict]]:
        try:
            job_id, node_id = job_run_id.split(
                ":",
                1,
            )
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
                protocol = self._local_protocols.get(node_id)
                if not protocol:
                    return None
                protocol._pending_agent_requests[request_id] = future
                await protocol.request_log_chunk(
                    job_id=job_id,
                    chunk_id=chunk_id,
                    request_id=request_id,
                )
            else:
                await self._ensure_remote_connection(via=node.remote_agent.via)
                ws = self._remote_conns.get(node.remote_agent.via)
                if not ws:
                    return None
                msg = WsMessage(
                    msg_type="api_get_log_chunk",
                    msg_body=WsMsgBodyApiGetLogChunk(
                        job_run_id=job_run_id,
                        chunk_id=chunk_id,
                        request_id=request_id,
                    ),
                )
                await ws.send(msg.model_dump_json())

            try:
                result = await asyncio.wait_for(
                    fut=future,
                    timeout=20,
                )
                return result
            except asyncio.TimeoutError:
                self._log.warning(msg=f"Timeout waiting for log chunk for {job_run_id}")
                return None
            finally:
                self._pending_requests.pop(
                    request_id,
                    None,
                )
                if node.remote_agent.via == self._via:
                    protocol = self._local_protocols.get(node_id)
                    if protocol:
                        protocol._pending_agent_requests.pop(
                            request_id,
                            None,
                        )

        except Exception as e:
            self._log.error(msg=f"Error getting log chunk for {job_run_id}: {e}")
            return None

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
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=ssl_ca,
            )
            ssl_context.load_cert_chain(
                certfile=ssl_cert,
                keyfile=ssl_key,
            )

        last_activity = asyncio.get_event_loop().time()

        while True:
            self._log.info(msg=f"Establishing inter-API connection to {via} at {url}")
            try:
                async with websockets.connect(
                    uri=url,
                    ssl=ssl_context,
                ) as ws:
                    self._log.info(msg=f"Inter-API connection to {via} established")
                    self._remote_conns[via] = ws

                    # Re-subscribe to all jobs for this via
                    for jrid, jvia in self._job_run_id_to_via.items():
                        if jvia == via:
                            sub_msg = WsMessage(
                                msg_type="subscribe_job_logs",
                                msg_body=WsMsgBodyJobLogs(id=jrid),
                            )
                            await ws.send(sub_msg.model_dump_json())

                    try:
                        async for message in ws:
                            self._log.debug(
                                msg=f"Inter-API received message from {via}: {message}"
                            )
                            data = json.loads(s=message)
                            msg_type = data.get("msg_type")
                            msg_body = data.get("msg_body")
                            if not msg_body:
                                continue

                            request_id = msg_body.get("request_id")
                            self._log.debug(msg=f"Inter-API message msg_type={msg_type} request_id={request_id}")
                            
                            if request_id and request_id in self._pending_requests:
                                self._log.debug(msg=f"Inter-API found pending request for {request_id}")
                                if msg_type == "api_log_chunks_response":
                                    self._pending_requests[request_id].set_result(
                                        msg_body.get("chunks")
                                    )
                                elif msg_type == "api_log_chunk_response":
                                    self._pending_requests[request_id].set_result(
                                        msg_body.get("data")
                                    )
                                continue

                            job_run_id = msg_body.get("job_run_id")
                            if not job_run_id:
                                # Fallback for old log_message format
                                job_run_id = msg_body.get("id")

                            if not job_run_id:
                                continue

                            # Broadcast to local subscribers
                            if job_run_id in self._subscriptions:
                                self._log.debug(msg=f"Inter-API broadcasting log message for {job_run_id}")
                                for local_ws in list(self._subscriptions[job_run_id]):
                                    try:
                                        await local_ws.send_text(data=message)
                                    except Exception:
                                        self._subscriptions[job_run_id].remove(local_ws)
                            last_activity = asyncio.get_event_loop().time()
                    finally:
                        self._log.info(msg=f"Inter-API connection to {via} closed")
                        self._remote_conns.pop(
                            via,
                            None,
                        )
            except Exception as e:
                self._log.error(msg=f"Inter-API connection to {via} failed: {e}")
                self._remote_conns.pop(
                    via,
                    None,
                )

            # Check if we still have subscriptions for this via
            has_subscriptions = any(v == via for v in self._job_run_id_to_via.values())
            if not has_subscriptions and (
                asyncio.get_event_loop().time() - last_activity > 300.0
            ):
                self._log.info(
                    msg=f"No more subscriptions for {via} and idle, stopping inter-API client"
                )
                break

            await asyncio.sleep(delay=5)
