import asyncio
import logging
import socket
import uuid
from typing import Dict
from typing import Set
from typing import Optional
from typing import Any
from typing import List

from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature
from itsdangerous import SignatureExpired

from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.model.ws import WsMessage
from pyppetdb.model.ws import WsMsgBodyLogMessage
from pyppetdb.model.ws import WsMsgBodyJobFinished
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodySubscribeLogs
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyUnsubscribeLogs


class WsAPI:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
    ):
        self._log = log
        self._config = config
        self._crud_nodes = crud_nodes
        self._via = socket.getfqdn()

        self._subscriptions: Dict[str, Set[WebSocket]] = {}
        self._job_run_id_to_via: Dict[str, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

        self._inter_api_client: Optional[Any] = None
        self._remote_executor: Optional[Any] = None

        self._serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey,
            salt=self._config.app.wssalt,
        )

    async def _get_lock(self, job_run_id: str) -> asyncio.Lock:
        async with self._locks_lock:
            if job_run_id not in self._locks:
                self._locks[job_run_id] = asyncio.Lock()
            return self._locks[job_run_id]

    @property
    def subscriptions(self):
        return self._subscriptions

    @property
    def job_run_id_to_via(self):
        return self._job_run_id_to_via

    def set_inter_api_client(self, client: Any):
        self._inter_api_client = client

    def set_remote_executor(self, remote_executor: Any):
        self._remote_executor = remote_executor

    async def endpoint(
        self,
        websocket: WebSocket,
    ):
        await websocket.accept()
        user_id = None
        subscriptions = set()
        try:
            while True:
                data = await websocket.receive_text()
                msg = WsMessage.model_validate_json(json_data=data)

                if msg.msg_type == "authenticate":
                    user_id = await self._handle_authenticate(
                        websocket=websocket,
                        token=msg.msg_body.token,
                    )
                    if user_id is None:
                        return
                elif user_id:
                    await self._handle_client_message(
                        websocket=websocket,
                        msg=msg,
                        subscriptions=subscriptions,
                    )
                else:
                    self._log.warning(
                        msg="WS logs received message before authentication"
                    )
                    await websocket.close(code=4003)
                    return
        except WebSocketDisconnect:
            pass
        except Exception as e:
            self._log.error(msg=f"WS logs error: {e}")
            await websocket.close(code=4003)
        finally:
            for job_run_id in list(subscriptions):
                await self.unsubscribe(
                    websocket=websocket,
                    job_run_id=job_run_id,
                )

    async def _handle_authenticate(self, websocket: WebSocket, token: str):
        try:
            token_data = self._serializer.loads(
                s=token,
                max_age=5,
            )
            user_id = token_data.get("user_id")
            self._log.info(msg=f"WS logs authenticated user: {user_id}")
            return user_id
        except (BadSignature, SignatureExpired) as e:
            self._log.error(msg=f"WS logs auth failed: {e}")
            await websocket.close(code=4003)
            return None

    async def _handle_client_message(
        self,
        websocket: WebSocket,
        msg: WsMessage,
        subscriptions: set,
    ):
        if msg.msg_type == "subscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self.subscribe(
                websocket=websocket,
                job_run_id=job_run_id,
            )
            subscriptions.add(job_run_id)
        elif msg.msg_type == "unsubscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self.unsubscribe(
                websocket=websocket,
                job_run_id=job_run_id,
            )
            subscriptions.discard(job_run_id)

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
            await self._broadcast_to_subscribers(job_run_id, msg.model_dump_json())

    async def broadcast_remote_message(self, job_run_id: str, data: str):
        if job_run_id in self._subscriptions:
            await self._broadcast_to_subscribers(job_run_id, data)

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

    async def subscribe(self, websocket: WebSocket, job_run_id: str):
        lock = await self._get_lock(job_run_id)
        async with lock:
            if (
                job_run_id in self._subscriptions
                and websocket in self._subscriptions[job_run_id]
            ):
                return

            is_first = False
            if job_run_id not in self._subscriptions:
                self._subscriptions[job_run_id] = set()
                is_first = True

            self._subscriptions[job_run_id].add(websocket)
            count = len(self._subscriptions[job_run_id])
            self._log.info(
                msg=f"WS: Client subscribed to {job_run_id} (total: {count})"
            )

            if not is_first:
                return

            try:
                job_id, node_id = job_run_id.split(":", 1)
                node = await self._crud_nodes.get(_id=node_id, fields=["remote_agent"])
                if node.remote_agent and node.remote_agent.connected:
                    if node.remote_agent.via != self._via:
                        self._job_run_id_to_via[job_run_id] = node.remote_agent.via
                        if self._inter_api_client:
                            self._log.info(
                                msg=f"WS: first subscription for {job_run_id}, subscribing via inter-API to {node.remote_agent.via}"
                            )
                            await self._inter_api_client.subscribe(
                                via=node.remote_agent.via,
                                job_run_id=job_run_id,
                            )
                    else:
                        self._log.info(
                            msg=f"WS: first subscription for {job_run_id}, subscribing to local agent"
                        )
                        await self._subscribe_local_agent(node_id, job_id)
            except Exception as e:
                self._log.error(msg=f"Error during subscribe for {job_run_id}: {e}")

    async def _subscribe_local_agent(self, node_id: str, job_id: str):
        if self._remote_executor:
            protocol = self._remote_executor.get_protocol(node_id)
            if protocol:
                await protocol._send_message(
                    msg_type="subscribe_logs",
                    body=RemoteExecutorMsgBodySubscribeLogs(job_id=job_id),
                )

    async def unsubscribe(self, websocket: WebSocket, job_run_id: str):
        lock = await self._get_lock(job_run_id)
        async with lock:
            if job_run_id not in self._subscriptions:
                return
            if websocket not in self._subscriptions[job_run_id]:
                return

            self._subscriptions[job_run_id].discard(websocket)
            count = len(self._subscriptions[job_run_id])
            self._log.info(
                msg=f"WS: Client unsubscribed from {job_run_id} (remaining: {count})"
            )
            if not self._subscriptions[job_run_id]:
                self._log.info(
                    msg=f"WS: Last subscriber left for {job_run_id}, cleaning up upstream"
                )
                await self._handle_last_unsubscription(job_run_id)

    async def _handle_last_unsubscription(self, job_run_id: str):
        self._subscriptions.pop(job_run_id, None)
        via = self._job_run_id_to_via.pop(job_run_id, None)

        if via:
            if self._inter_api_client:
                self._log.info(
                    msg=f"WS: unsubscribing from inter-API {via} for {job_run_id}"
                )
                await self._inter_api_client.unsubscribe(
                    via=via,
                    job_run_id=job_run_id,
                )
        else:
            self._log.info(msg=f"WS: unsubscribing from local agent for {job_run_id}")
            await self._unsubscribe_local_agent(job_run_id)

    async def _unsubscribe_local_agent(self, job_run_id: str):
        try:
            job_id, node_id = job_run_id.split(":", 1)
            if self._remote_executor:
                protocol = self._remote_executor.get_protocol(node_id)
                if protocol:
                    await protocol._send_message(
                        msg_type="unsubscribe_logs",
                        body=RemoteExecutorMsgBodyUnsubscribeLogs(job_id=job_id),
                    )
        except Exception as e:
            self._log.error(msg=f"Error sending unsubscribe_logs to local agent: {e}")

    async def get_log_chunks(self, job_run_id: str) -> List[str]:
        try:
            job_id, node_id = job_run_id.split(":", 1)
            node = await self._crud_nodes.get(_id=node_id, fields=["remote_agent"])
            if not node.remote_agent or not node.remote_agent.connected:
                return []

            request_id = str(uuid.uuid4())
            future = asyncio.get_event_loop().create_future()

            if node.remote_agent.via == self._via:
                if self._remote_executor:
                    await self._remote_executor.get_log_chunks(
                        node_id, job_id, request_id, future
                    )
                else:
                    return []
            elif self._inter_api_client:
                await self._inter_api_client.get_log_chunks(
                    via=node.remote_agent.via,
                    job_run_id=job_run_id,
                    request_id=request_id,
                    future=future,
                )
            else:
                return []

            try:
                return await asyncio.wait_for(fut=future, timeout=20)
            except asyncio.TimeoutError:
                self._log.warning(
                    msg=f"Timeout waiting for log chunks for {job_run_id}"
                )
                return []
            finally:
                if node.remote_agent.via == self._via and self._remote_executor:
                    self._remote_executor.cleanup_request(node_id, request_id)

        except Exception as e:
            self._log.error(msg=f"Error getting log chunks for {job_run_id}: {e}")
            return []

    async def get_log_chunk(
        self,
        job_run_id: str,
        chunk_id: str,
    ) -> Optional[List[Dict]]:
        try:
            job_id, node_id = job_run_id.split(":", 1)
            node = await self._crud_nodes.get(_id=node_id, fields=["remote_agent"])
            if not node.remote_agent or not node.remote_agent.connected:
                return None

            request_id = str(uuid.uuid4())
            future = asyncio.get_event_loop().create_future()

            if node.remote_agent.via == self._via:
                if self._remote_executor:
                    await self._remote_executor.get_log_chunk(
                        node_id, job_id, chunk_id, request_id, future
                    )
                else:
                    return None
            elif self._inter_api_client:
                await self._inter_api_client.get_log_chunk(
                    via=node.remote_agent.via,
                    job_run_id=job_run_id,
                    chunk_id=chunk_id,
                    request_id=request_id,
                    future=future,
                )
            else:
                return None

            try:
                return await asyncio.wait_for(fut=future, timeout=20)
            except asyncio.TimeoutError:
                self._log.warning(msg=f"Timeout waiting for log chunk for {job_run_id}")
                return None
            finally:
                if node.remote_agent.via == self._via and self._remote_executor:
                    self._remote_executor.cleanup_request(node_id, request_id)

        except Exception as e:
            self._log.error(msg=f"Error getting log chunk for {job_run_id}: {e}")
            return None
