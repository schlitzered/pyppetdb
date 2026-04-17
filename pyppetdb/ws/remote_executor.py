import asyncio
import logging
import random
import time
from typing import Dict, List, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError, BaseModel

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.errors import ClientCertError
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor

from pyppetdb.model.remote_executor import RemoteExecutorMessage
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyAck
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyLogMessage
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyFinish
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyStatus
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyStartJob
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyHeartbeat
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyGetLogChunks
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyLogChunks
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyGetLogChunk
from pyppetdb.model.remote_executor import RemoteExecutorMsgBodyLogChunkData


class RemoteExecutorLogHandler:
    def __init__(
        self,
        log: logging.Logger,
        node_id: str,
        redactor: NodesSecretsRedactor,
        manager: Any,
    ):
        self._log = log
        self._node_id = node_id
        self._redactor = redactor
        self._manager = manager

    async def handle_log_message(
        self,
        body: RemoteExecutorMsgBodyLogMessage,
        current_job_id: Optional[str],
    ):
        for log_entry in body.logs:
            entry_dict = log_entry.model_dump()
            entry_dict["msg"] = self._redactor.redact(entry_dict["msg"])
            if current_job_id:
                await self._manager.broadcast_local_log(
                    node_id=self._node_id,
                    job_id=current_job_id,
                    log_entry=entry_dict,
                )


class RemoteExecutorJobManager:
    def __init__(
        self,
        log: logging.Logger,
        node_id: str,
        crud_nodes: CrudNodes,
        crud_jobs: CrudJobs,
        crud_job_definitions: CrudJobsDefinitions,
        crud_node_jobs: CrudJobsNodeJobs,
        manager: Any,
    ):
        self._log = log
        self._node_id = node_id
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._manager = manager

        self.busy = False
        self.current_job_id: Optional[str] = None

    async def initialize(self):
        node = await self._crud_nodes.get(
            _id=self._node_id,
            fields=["remote_agent"],
        )
        if node.remote_agent:
            self.busy = node.remote_agent.busy
            self.current_job_id = node.remote_agent.current_job_id

        await self._cleanup_stale_jobs()

    async def _cleanup_stale_jobs(self):
        try:
            running_jobs = await self._crud_node_jobs.search(
                node_id=self._node_id,
                status="running",
            )
            for job in running_jobs.result:
                if job.job_id != self.current_job_id:
                    self._log.warning(
                        msg=f"Found stale running job {job.job_id} for node {self._node_id} during startup. Marking as failed."
                    )
                    await self.mark_job_failed(
                        job_id=job.job_id,
                        reason="Stale job found during protocol startup",
                    )
        except Exception as e:
            self._log.error(
                msg=f"Error checking for stale jobs during startup for {self._node_id}: {e}"
            )

    async def handle_finish(
        self,
        body: RemoteExecutorMsgBodyFinish,
    ):
        exit_code = body.exit_code
        status = "success" if exit_code == 0 else "failed"

        if self.current_job_id:
            await self._crud_node_jobs.update_status(
                job_id=self.current_job_id,
                node_id=self._node_id,
                status=status,
            )
            await self._manager.job_finished(
                node_id=self._node_id,
                job_id=self.current_job_id,
                status=status,
                exit_code=exit_code,
            )

        await self.mark_node_not_busy()

    async def handle_status(
        self,
        body: RemoteExecutorMsgBodyStatus,
    ):
        if not body.busy and self.current_job_id:
            self._log.warning(
                msg=f"Agent {self._node_id} reported NOT busy, but we thought it was running {self.current_job_id}. Marking job as failed."
            )
            await self.mark_current_job_failed(reason="Agent reported not busy")

        self.busy = body.busy
        self.current_job_id = body.current_job_id
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=self.busy,
            current_job_id=self.current_job_id,
        )

    async def mark_current_job_failed(
        self,
        reason: str,
    ):
        if not self.current_job_id:
            return
        await self.mark_job_failed(
            job_id=self.current_job_id,
            reason=reason,
        )
        await self.mark_node_not_busy()

    async def mark_job_failed(
        self,
        job_id: str,
        reason: str,
    ):
        self._log.warning(
            msg=f"Marking job {job_id} for node {self._node_id} as failed: {reason}"
        )

        await self._crud_node_jobs.update_status(
            job_id=job_id,
            node_id=self._node_id,
            status="failed",
        )
        await self._manager.job_finished(
            node_id=self._node_id,
            job_id=job_id,
            status="failed",
            exit_code=1,
        )

    async def mark_node_not_busy(self):
        self.busy = False
        self.current_job_id = None
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=False,
            current_job_id=None,
        )

    async def start_job(
        self,
        node_job,
    ) -> RemoteExecutorMsgBodyStartJob:
        job = await self._crud_jobs.get(
            _id=node_job.job_id,
            fields=[],
        )
        definition = await self._crud_job_definitions.get(
            _id=job.definition_id,
            fields=[],
        )

        self.busy = True
        self.current_job_id = node_job.job_id
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=True,
            current_job_id=self.current_job_id,
        )
        await self._crud_node_jobs.update_status(
            job_id=self.current_job_id,
            node_id=self._node_id,
            status="running",
        )

        return RemoteExecutorMsgBodyStartJob(
            job_id=node_job.job_id,
            executable=definition.executable,
            user=definition.user,
            group=definition.group,
            params_template=definition.params_template,
            parameters=job.parameters,
            env_vars=job.env_vars,
        )


class RemoteExecutorProtocol:
    def __init__(
        self,
        log: logging.Logger,
        node_id: str,
        websocket: WebSocket,
        crud_nodes: CrudNodes,
        crud_jobs: CrudJobs,
        crud_job_definitions: CrudJobsDefinitions,
        crud_node_jobs: CrudJobsNodeJobs,
        redactor: NodesSecretsRedactor,
        manager: Any,
    ):
        self._log = log
        self._node_id = node_id
        self._websocket = websocket
        self._crud_node_jobs = crud_node_jobs

        self._log_handler = RemoteExecutorLogHandler(
            log=log,
            node_id=node_id,
            redactor=redactor,
            manager=manager,
        )
        self._job_manager = RemoteExecutorJobManager(
            log=log,
            node_id=node_id,
            crud_nodes=crud_nodes,
            crud_jobs=crud_jobs,
            crud_job_definitions=crud_job_definitions,
            crud_node_jobs=crud_node_jobs,
            manager=manager,
        )

        self._msg_id_counter = 0
        self._pending_acks: Dict[int, asyncio.Event] = {}
        self._running = True
        self._last_activity = time.time()
        self._heartbeat_interval = 30

        self._pending_agent_requests: Dict[str, asyncio.Future] = {}

    @property
    def pending_agent_requests(self):
        return self._pending_agent_requests

    def stop(self):
        self._running = False

    async def run(self):
        await self._job_manager.initialize()

        polling_task = asyncio.create_task(coro=self._poll_for_jobs())
        heartbeat_task = asyncio.create_task(coro=self._heartbeat())

        try:
            while self._running:
                data = await self._websocket.receive_text()
                self._last_activity = time.time()
                await self._handle_message(data=data)
        except WebSocketDisconnect:
            self._log.info(msg=f"Agent {self._node_id} disconnected")
            raise
        except Exception as e:
            self._log.error(msg=f"Error in protocol for {self._node_id}: {e}")
            raise
        finally:
            self._running = False
            polling_task.cancel()
            heartbeat_task.cancel()
            try:
                await asyncio.gather(
                    polling_task,
                    heartbeat_task,
                    return_exceptions=True,
                )
            except Exception:
                pass

    async def _handle_message(
        self,
        data: str,
    ):
        try:
            msg = RemoteExecutorMessage.model_validate_json(json_data=data)
            msg_type = msg.msg_type
            msg_id = msg.msg_id
            body = msg.msg_body

            if msg_type == "ack":
                if isinstance(body, RemoteExecutorMsgBodyAck):
                    for aid in body.acked_ids:
                        if aid in self._pending_acks:
                            self._pending_acks[aid].set()
                return

            if msg_id is not None:
                await self._send_ack(acked_ids=[msg_id])

            if msg_type == "log_message" and isinstance(
                body, RemoteExecutorMsgBodyLogMessage
            ):
                await self._log_handler.handle_log_message(
                    body=body,
                    current_job_id=self._job_manager.current_job_id,
                )
            elif msg_type == "finish" and isinstance(body, RemoteExecutorMsgBodyFinish):
                await self._job_manager.handle_finish(body=body)
            elif msg_type == "status" and isinstance(body, RemoteExecutorMsgBodyStatus):
                await self._job_manager.handle_status(body=body)
            elif msg_type == "log_chunks" and isinstance(
                body, RemoteExecutorMsgBodyLogChunks
            ):
                await self._handle_log_chunks(body=body)
            elif msg_type == "log_chunk_data" and isinstance(
                body, RemoteExecutorMsgBodyLogChunkData
            ):
                await self._handle_log_chunk_data(body=body)
            elif msg_type == "heartbeat":
                pass
            else:
                self._log.warning(
                    msg=f"Unknown or malformed message type from {self._node_id}: {msg_type}"
                )

        except ValidationError as e:
            self._log.error(msg=f"Validation error from {self._node_id}: {e}")
        except Exception as e:
            self._log.error(msg=f"Error handling message from {self._node_id}: {e}")

    async def _handle_log_chunks(
        self,
        body: RemoteExecutorMsgBodyLogChunks,
    ):
        if body.request_id in self.pending_agent_requests:
            self.pending_agent_requests[body.request_id].set_result(body.chunks)

    async def _handle_log_chunk_data(
        self,
        body: RemoteExecutorMsgBodyLogChunkData,
    ):
        if body.request_id in self.pending_agent_requests:
            self.pending_agent_requests[body.request_id].set_result(
                [log.model_dump() for log in body.data]
            )

    async def request_log_chunks(
        self,
        job_id: str,
        request_id: str,
    ):
        body = RemoteExecutorMsgBodyGetLogChunks(
            job_id=job_id,
            request_id=request_id,
        )
        await self._send_message(
            msg_type="get_log_chunks",
            body=body,
        )

    async def request_log_chunk(
        self,
        job_id: str,
        chunk_id: str,
        request_id: str,
    ):
        body = RemoteExecutorMsgBodyGetLogChunk(
            job_id=job_id,
            chunk_id=chunk_id,
            request_id=request_id,
        )
        await self._send_message(
            msg_type="get_log_chunk",
            body=body,
        )

    async def _heartbeat(self):
        while self._running:
            await asyncio.sleep(delay=self._heartbeat_interval)
            if time.time() - self._last_activity >= self._heartbeat_interval:
                await self._send_message(
                    msg_type="heartbeat",
                    body=RemoteExecutorMsgBodyHeartbeat(),
                )

    async def _poll_for_jobs(self):
        while self._running:
            if not self._job_manager.busy:
                node_job = await self._crud_node_jobs.get_oldest_scheduled(
                    node_id=self._node_id
                )
                if node_job:
                    msg_body = await self._job_manager.start_job(node_job=node_job)
                    await self._send_message(
                        msg_type="start_job",
                        body=msg_body,
                    )

            await asyncio.sleep(delay=random.randint(a=30, b=60))

    async def _send_message(
        self,
        msg_type: str,
        body: BaseModel,
    ):
        msg_id = self._msg_id_counter
        self._msg_id_counter += 1

        msg = RemoteExecutorMessage(
            msg_id=msg_id,
            msg_type=msg_type,
            msg_body=body,
        )

        ack_event = asyncio.Event()
        self._pending_acks[msg_id] = ack_event

        await self._websocket.send_text(data=msg.model_dump_json())
        self._last_activity = time.time()

        try:
            await asyncio.wait_for(
                fut=ack_event.wait(),
                timeout=10,
            )
        except asyncio.TimeoutError:
            self._log.warning(
                msg=f"Timeout waiting for ACK for msg_id {msg_id} from {self._node_id}"
            )
        finally:
            self._pending_acks.pop(
                msg_id,
                None,
            )

    async def _send_ack(
        self,
        acked_ids: List[int],
    ):
        msg_body = RemoteExecutorMsgBodyAck(acked_ids=acked_ids)
        msg = RemoteExecutorMessage(
            msg_type="ack",
            msg_body=msg_body,
        )
        await self._websocket.send_text(data=msg.model_dump_json())
        self._last_activity = time.time()


class WsRemoteExecutor:
    def __init__(
        self,
        log: logging.Logger,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes: CrudNodes,
        crud_jobs: CrudJobs,
        crud_job_definitions: CrudJobsDefinitions,
        crud_node_jobs: CrudJobsNodeJobs,
        redactor: NodesSecretsRedactor,
        api: Any,
        via: str,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._redactor = redactor
        self._api = api
        self._via = via

        self._local_protocols: Dict[str, RemoteExecutorProtocol] = {}

    def register_protocol(self, node_id: str, protocol: RemoteExecutorProtocol):
        old_protocol = self._local_protocols.get(node_id)
        if old_protocol:
            self._log.info(msg=f"Stopping existing protocol for node {node_id}")
            old_protocol.stop()
        self._local_protocols[node_id] = protocol

    def unregister_protocol(self, node_id: str):
        self._local_protocols.pop(node_id, None)

    def get_protocol(self, node_id: str) -> Optional[RemoteExecutorProtocol]:
        return self._local_protocols.get(node_id)

    async def get_log_chunks(
        self,
        node_id: str,
        job_id: str,
        request_id: str,
        future: asyncio.Future,
    ):
        protocol = self.get_protocol(node_id)
        if not protocol:
            future.set_result([])
            return
        protocol.pending_agent_requests[request_id] = future
        await protocol.request_log_chunks(job_id=job_id, request_id=request_id)

    async def get_log_chunk(
        self,
        node_id: str,
        job_id: str,
        chunk_id: str,
        request_id: str,
        future: asyncio.Future,
    ):
        protocol = self.get_protocol(node_id)
        if not protocol:
            future.set_result(None)
            return
        protocol.pending_agent_requests[request_id] = future
        await protocol.request_log_chunk(
            job_id=job_id,
            chunk_id=chunk_id,
            request_id=request_id,
        )

    def cleanup_request(self, node_id: str, request_id: str):
        protocol = self.get_protocol(node_id)
        if protocol:
            protocol.pending_agent_requests.pop(request_id, None)

    async def endpoint(
        self,
        websocket: WebSocket,
        node_id: str,
    ):
        try:
            await websocket.accept()
            await self._authorize_client_cert.require_cn_match(
                request=websocket,
                match=node_id,
            )

            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id,
                connected=True,
                via=self._via,
            )

            protocol = RemoteExecutorProtocol(
                log=self._log,
                node_id=node_id,
                websocket=websocket,
                crud_nodes=self._crud_nodes,
                crud_jobs=self._crud_jobs,
                crud_job_definitions=self._crud_job_definitions,
                crud_node_jobs=self._crud_node_jobs,
                redactor=self._redactor,
                manager=self._api,
            )

            self.register_protocol(node_id=node_id, protocol=protocol)
            await protocol.run()

        except ClientCertError as e:
            self._log.error(msg=f"WS remote_executor Auth failed: {e.detail}")
            await websocket.close(code=4003)
        except WebSocketDisconnect:
            await self._handle_disconnect(node_id)
        except Exception as e:
            self._log.error(msg=f"WS remote_executor unexpected error: {e}")
            await self._handle_disconnect(node_id)
            await websocket.close(code=4003)

    async def _handle_disconnect(self, node_id: str):
        self.unregister_protocol(node_id=node_id)
        await self._crud_nodes.update_remote_agent_status(
            node_id=node_id,
            connected=False,
            via=None,
        )
