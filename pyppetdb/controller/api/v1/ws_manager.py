import asyncio
import logging
import json
import socket
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket

from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.jobs_nodes_jobs_logs import CrudJobsNodesLogsLogBlobs
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.model.ws import (
    WsMessage,
    WsMsgBodyLogMessage,
    WsMsgBodyJobFinished,
    WsMsgBodyJobLogs,
)


class LogSubscriptionManager:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_node_jobs: CrudJobsNodeJobs,
        crud_log_blobs: CrudJobsNodesLogsLogBlobs,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
    ):
        self._log = log
        self._config = config
        self._crud_nodes = crud_nodes
        self._crud_node_jobs = crud_node_jobs
        self._crud_log_blobs = crud_log_blobs
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

    def register_protocol(self, node_id: str, protocol: Any):
        self._local_protocols[node_id] = protocol

    def unregister_protocol(self, node_id: str):
        self._local_protocols.pop(node_id, None)

    async def broadcast_local_log(self, node_id: str, job_id: str, log_entry: Dict):
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
                    await ws.send_text(data)
                except Exception:
                    self._subscriptions[job_run_id].remove(ws)

    async def job_finished(
        self, node_id: str, job_id: str, status: str, exit_code: Optional[int] = None
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
                    await ws.send_text(data)
                except Exception:
                    self._subscriptions[job_run_id].remove(ws)

    async def subscribe(self, websocket: WebSocket, job_run_id: str):
        if job_run_id not in self._subscriptions:
            self._subscriptions[job_run_id] = set()
        self._subscriptions[job_run_id].add(websocket)

        # 1. Fetch existing logs from DB
        try:
            node_job = await self._crud_node_jobs.get(
                _id=job_run_id,
                fields=["id", "job_id", "node_id", "status", "log_blobs"],
            )
            for blob_id in node_job.log_blobs:
                blob = await self._crud_log_blobs.get(_id=blob_id, fields=["data"])
                if blob.data:
                    msg = WsMessage(
                        msg_type="log_message",
                        msg_body=WsMsgBodyLogMessage(
                            job_run_id=job_run_id,
                            logs=blob.data,
                        ),
                    )
                    await websocket.send_text(msg.model_dump_json())
        except Exception as e:
            self._log.error(f"Error fetching existing logs for {job_run_id}: {e}")

        # 2. Determine if local or remote
        try:
            job_id, node_id = job_run_id.split(":", 1)
            node = await self._crud_nodes.get(_id=node_id, fields=["remote_agent"])
            if node.remote_agent and node.remote_agent.connected:
                if node.remote_agent.via == self._via:
                    # Local: Protocol will push logs
                    protocol = self._local_protocols.get(node_id)
                    if protocol and protocol._log_buffer:
                        msg = WsMessage(
                            msg_type="log_message",
                            msg_body=WsMsgBodyLogMessage(
                                job_run_id=job_run_id,
                                logs=protocol._log_buffer,
                            ),
                        )
                        await websocket.send_text(msg.model_dump_json())
                else:
                    # Remote: Connect to another API server if not already connected
                    self._job_run_id_to_via[job_run_id] = node.remote_agent.via
                    await self._ensure_remote_subscription(
                        job_run_id, node.remote_agent.via
                    )
        except Exception as e:
            self._log.error(f"Error determining local/remote for {job_run_id}: {e}")

    async def unsubscribe(self, websocket: WebSocket, job_run_id: str):
        if job_run_id in self._subscriptions:
            self._subscriptions[job_run_id].discard(websocket)
            if not self._subscriptions[job_run_id]:
                del self._subscriptions[job_run_id]
                via = self._job_run_id_to_via.pop(job_run_id, None)
                if via:
                    await self._remote_unsubscribe(job_run_id, via)

    async def _remote_unsubscribe(self, job_run_id: str, via: str):
        ws = self._remote_conns.get(via)
        if ws:
            unsub_msg = WsMessage(
                msg_type="unsubscribe_job_logs",
                msg_body=WsMsgBodyJobLogs(id=job_run_id),
            )
            data = unsub_msg.model_dump_json()
            try:
                self._log.info(f"Sending unsubscription for {job_run_id} to {via}")
                await ws.send(data)
            except Exception as e:
                self._log.error(f"Failed to send unsubscription to {via}: {e}")

    async def _ensure_remote_subscription(self, job_run_id: str, via: str):
        if via not in self._remote_locks:
            self._remote_locks[via] = asyncio.Lock()

        async with self._remote_locks[via]:
            if via not in self._remote_conns:
                # Start a background task to handle remote connection
                asyncio.create_task(self._remote_api_client(via))
                # Wait a bit for connection to be established
                for _ in range(20):
                    if via in self._remote_conns:
                        break
                    await asyncio.sleep(0.1)

            ws = self._remote_conns.get(via)
            if ws:
                sub_msg = WsMessage(
                    msg_type="subscribe_job_logs",
                    msg_body=WsMsgBodyJobLogs(id=job_run_id),
                )
                data = sub_msg.model_dump_json()
                self._log.info(f"Sending subscription for {job_run_id} to {via}")
                try:
                    await ws.send(data)
                except Exception as e:
                    self._log.error(
                        f"Failed to send subscription for {job_run_id} to {via}: {e}"
                    )

    async def _remote_api_client(self, via: str):
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
                ssl.Purpose.SERVER_AUTH, cafile=ssl_ca
            )
            ssl_context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)

        while True:
            self._log.info(f"Establishing inter-API connection to {via} at {url}")
            try:
                async with websockets.connect(url, ssl=ssl_context) as ws:
                    self._log.info(f"Inter-API connection to {via} established")
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
                                f"Inter-API received message from {via}: {message}"
                            )
                            data = json.loads(message)
                            msg_body = data.get("msg_body")
                            if not msg_body:
                                continue

                            job_run_id = msg_body.get("job_run_id")
                            if not job_run_id:
                                continue

                            # Broadcast to local subscribers
                            if job_run_id in self._subscriptions:
                                for local_ws in list(self._subscriptions[job_run_id]):
                                    try:
                                        await local_ws.send_text(message)
                                    except Exception:
                                        self._subscriptions[job_run_id].remove(local_ws)
                    finally:
                        self._log.info(f"Inter-API connection to {via} closed")
                        self._remote_conns.pop(via, None)
            except Exception as e:
                self._log.error(f"Inter-API connection to {via} failed: {e}")
                self._remote_conns.pop(via, None)

            # Check if we still have subscriptions for this via
            has_subscriptions = any(v == via for v in self._job_run_id_to_via.values())
            if not has_subscriptions:
                self._log.info(
                    f"No more subscriptions for {via}, stopping inter-API client"
                )
                break

            await asyncio.sleep(5)
