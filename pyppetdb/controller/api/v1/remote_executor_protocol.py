import asyncio
import base64
import gzip
import logging
import random
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError, BaseModel

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.jobs_nodes_jobs_logs import CrudJobsNodesLogsLogBlobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.model.remote_executor import (
    RemoteExecutorMessage,
    RemoteExecutorMsgBodyAck,
    RemoteExecutorMsgBodyLogMessage,
    RemoteExecutorMsgBodyFinish,
    RemoteExecutorMsgBodyStatus,
    RemoteExecutorMsgBodyStartJob,
    RemoteExecutorMsgBodyHeartbeat,
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
        crud_log_blobs: CrudJobsNodesLogsLogBlobs,
        redactor: NodesSecretsRedactor,
        manager: Any,
    ):
        self._log = log
        self._node_id = node_id
        self._websocket = websocket
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._crud_log_blobs = crud_log_blobs
        self._redactor = redactor
        self._manager = manager

        self._msg_id_counter = 0
        self._pending_acks: Dict[int, asyncio.Event] = {}
        self._log_buffer: List[Dict] = []
        self._busy = False
        self._current_job_id: Optional[str] = None
        self._running = True
        self._last_activity = time.time()
        self._heartbeat_interval = 30

    def stop(self):
        self._running = False

    async def run(self):
        # 1. Fetch node state
        node = await self._crud_nodes.get(
            _id=self._node_id,
            fields=["remote_agent"],
        )
        if node.remote_agent:
            self._busy = node.remote_agent.busy
            self._current_job_id = node.remote_agent.current_job_id

        # 2. Cleanup ANY jobs that are 'running' in the database but are NOT self._current_job_id
        #    This handles the case where the API server crashed or some inconsistency occurred.
        try:
            running_jobs = await self._crud_node_jobs.search(
                node_id=self._node_id,
                status="running"
            )
            for job in running_jobs.result:
                if job.job_id != self._current_job_id:
                    self._log.warning(f"Found stale running job {job.job_id} for node {self._node_id} during startup. Marking as failed.")
                    await self._mark_job_failed(job_id=job.job_id, reason="Stale job found during protocol startup")
        except Exception as e:
            self._log.error(f"Error checking for stale jobs during startup for {self._node_id}: {e}")

        polling_task = asyncio.create_task(self._poll_for_jobs())
        heartbeat_task = asyncio.create_task(self._heartbeat())

        try:
            while self._running:
                data = await self._websocket.receive_text()
                self._last_activity = time.time()
                await self._handle_message(data=data)
        except WebSocketDisconnect:
            self._log.info(f"Agent {self._node_id} disconnected")
            raise
        except Exception as e:
            self._log.error(f"Error in protocol for {self._node_id}: {e}")
            raise
        finally:
            self._running = False
            polling_task.cancel()
            heartbeat_task.cancel()
            try:
                await asyncio.gather(
                    polling_task, heartbeat_task, return_exceptions=True
                )
            except Exception:
                pass

    async def _handle_message(self, data: str):
        try:
            msg = RemoteExecutorMessage.model_validate_json(data)
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
                await self._handle_log_message(body=body)
            elif msg_type == "finish" and isinstance(body, RemoteExecutorMsgBodyFinish):
                await self._handle_finish(body=body)
            elif msg_type == "status" and isinstance(body, RemoteExecutorMsgBodyStatus):
                await self._handle_status(body=body)
            elif msg_type == "heartbeat":
                pass
            else:
                self._log.warning(
                    f"Unknown or malformed message type from {self._node_id}: {msg_type}"
                )

        except ValidationError as e:
            self._log.error(f"Validation error from {self._node_id}: {e}")
        except Exception as e:
            self._log.error(f"Error handling message from {self._node_id}: {e}")

    async def _handle_log_message(self, body: RemoteExecutorMsgBodyLogMessage):
        for log_entry in body.logs:
            entry_dict = log_entry.model_dump()
            entry_dict["msg"] = self._redactor.redact(entry_dict["msg"])
            self._log_buffer.append(entry_dict)
            await self._publish_log(log_entry=entry_dict)

        if len(self._log_buffer) >= 1000:
            await self._flush_logs()

    async def _publish_log(self, log_entry: Dict):
        if self._current_job_id:
            await self._manager.broadcast_local_log(
                node_id=self._node_id,
                job_id=self._current_job_id,
                log_entry=log_entry,
            )

    async def _flush_logs(self):
        if not self._log_buffer or not self._current_job_id:
            return

        logs_to_flush = self._log_buffer[:1000]
        self._log_buffer = self._log_buffer[1000:]

        # Use pydantic friendly datetime serialization (json.dumps with custom or default)
        def datetime_handler(x):
            if isinstance(x, (time.struct_time, datetime)):
                return x.isoformat()
            return str(x)

        import json

        json_data = json.dumps(logs_to_flush, default=datetime_handler)
        compressed = gzip.compress(json_data.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")

        blob_id = str(uuid.uuid4())
        await self._crud_log_blobs.create(
            _id=blob_id,
            data=encoded,
        )
        await self._crud_node_jobs.add_log_blob(
            job_id=self._current_job_id,
            node_id=self._node_id,
            blob_id=blob_id,
        )

    async def _handle_finish(self, body: RemoteExecutorMsgBodyFinish):
        exit_code = body.exit_code
        status = "success" if exit_code == 0 else "failed"

        if self._current_job_id:
            while self._log_buffer:
                await self._flush_logs()

            await self._crud_node_jobs.update_status(
                job_id=self._current_job_id,
                node_id=self._node_id,
                status=status,
            )
            await self._manager.job_finished(
                node_id=self._node_id,
                job_id=self._current_job_id,
                status=status,
                exit_code=exit_code,
            )

        await self._mark_node_not_busy()

    async def _handle_status(self, body: RemoteExecutorMsgBodyStatus):
        if not body.busy and self._current_job_id:
            self._log.warning(f"Agent {self._node_id} reported NOT busy, but we thought it was running {self._current_job_id}. Marking job as failed.")
            await self._mark_current_job_failed(reason="Agent reported not busy")

        self._busy = body.busy
        self._current_job_id = body.current_job_id
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=self._busy,
            current_job_id=self._current_job_id,
        )

    async def _mark_current_job_failed(self, reason: str):
        if not self._current_job_id:
            return
        await self._mark_job_failed(job_id=self._current_job_id, reason=reason)
        await self._mark_node_not_busy()

    async def _mark_job_failed(self, job_id: str, reason: str):
        self._log.warning(f"Marking job {job_id} for node {self._node_id} as failed: {reason}")
        
        # Flush any pending logs for this job if possible
        if self._current_job_id == job_id:
            while self._log_buffer:
                await self._flush_logs()

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

    async def _mark_node_not_busy(self):
        self._busy = False
        self._current_job_id = None
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=False,
            current_job_id=None,
        )

    async def _heartbeat(self):
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            if time.time() - self._last_activity >= self._heartbeat_interval:
                await self._send_message(
                    msg_type="heartbeat", body=RemoteExecutorMsgBodyHeartbeat()
                )

    async def _poll_for_jobs(self):
        while self._running:
            if not self._busy:
                node_job = await self._crud_node_jobs.get_oldest_scheduled(
                    node_id=self._node_id
                )
                if node_job:
                    await self._start_job(node_job=node_job)

            await asyncio.sleep(random.randint(30, 60))

    async def _start_job(self, node_job):
        job = await self._crud_jobs.get(
            _id=node_job.job_id,
            fields=[],
        )
        definition = await self._crud_job_definitions.get(
            _id=job.definition_id,
            fields=[],
        )

        self._busy = True
        self._current_job_id = node_job.job_id
        await self._crud_nodes.update_remote_agent_busy(
            node_id=self._node_id,
            busy=True,
            current_job_id=self._current_job_id,
        )
        await self._crud_node_jobs.update_status(
            job_id=self._current_job_id,
            node_id=self._node_id,
            status="running",
        )

        msg_body = RemoteExecutorMsgBodyStartJob(
            job_id=node_job.job_id,
            executable=definition.executable,
            user=definition.user,
            group=definition.group,
            params_template=definition.params_template,
            parameters=job.parameters,
            env_vars=job.env_vars,
        )
        await self._send_message(
            msg_type="start_job",
            body=msg_body,
        )

    async def _send_message(self, msg_type: str, body: BaseModel):
        msg_id = self._msg_id_counter
        self._msg_id_counter += 1

        msg = RemoteExecutorMessage(
            msg_id=msg_id,
            msg_type=msg_type,  # type: ignore
            msg_body=body,
        )

        ack_event = asyncio.Event()
        self._pending_acks[msg_id] = ack_event

        await self._websocket.send_text(msg.model_dump_json())
        self._last_activity = time.time()

        try:
            await asyncio.wait_for(
                ack_event.wait(),
                timeout=10,
            )
        except asyncio.TimeoutError:
            self._log.warning(
                f"Timeout waiting for ACK for msg_id {msg_id} from {self._node_id}"
            )
        finally:
            self._pending_acks.pop(msg_id, None)

    async def _send_ack(self, acked_ids: List[int]):
        msg_body = RemoteExecutorMsgBodyAck(acked_ids=acked_ids)
        msg = RemoteExecutorMessage(
            msg_type="ack",
            msg_body=msg_body,
        )
        await self._websocket.send_text(msg.model_dump_json())
        self._last_activity = time.time()
