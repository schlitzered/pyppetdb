import asyncio
import os
import sys
import socket
import ssl
import time
from datetime import datetime
from typing import Dict, Set, List, Optional, Any, Union, Literal
import argparse
import websockets
from pydantic import ValidationError
import json

from cryptography import x509
from cryptography.hazmat.backends import default_backend

# We can't easily import from pyppetdb if it's not installed,
# so we redefine the necessary parts of the protocol models here for the client.
from pydantic import BaseModel, model_validator, ConfigDict


class RemoteExecutorLogEntry(BaseModel):
    line_nr: int
    timestamp: datetime
    msg: str


class RemoteExecutorMsgBodyLogMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logs: List[RemoteExecutorLogEntry]


class RemoteExecutorMsgBodyAck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acked_ids: List[int]


class RemoteExecutorMsgBodyFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exit_code: int


class RemoteExecutorMsgBodyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    busy: bool
    current_job_id: Optional[str] = None


class RemoteExecutorMsgBodyHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteExecutorMsgBodyStartJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    executable: str
    user: str
    group: str
    params_template: List[str]
    parameters: Dict[str, Any]
    env_vars: Dict[str, str]


class RemoteExecutorMsgBodyGetLogChunks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    request_id: str


class RemoteExecutorMsgBodyLogChunks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    request_id: str
    chunks: List[str]


class RemoteExecutorMsgBodyGetLogChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    chunk_id: str
    request_id: str


class RemoteExecutorMsgBodyLogChunkData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    chunk_id: str
    request_id: str
    data: List[RemoteExecutorLogEntry]


class RemoteExecutorMsgBodyJobId(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str


RemoteExecutorMsgBodySubscribeLogs = RemoteExecutorMsgBodyJobId
RemoteExecutorMsgBodyUnsubscribeLogs = RemoteExecutorMsgBodyJobId


class RemoteExecutorMessage(BaseModel):
    msg_id: Optional[int] = None
    msg_type: Literal[
        "log_message",
        "ack",
        "finish",
        "status",
        "heartbeat",
        "start_job",
        "get_log_chunks",
        "log_chunks",
        "get_log_chunk",
        "log_chunk_data",
        "subscribe_logs",
        "unsubscribe_logs",
    ]
    msg_body: Union[
        RemoteExecutorMsgBodyLogMessage,
        RemoteExecutorMsgBodyAck,
        RemoteExecutorMsgBodyFinish,
        RemoteExecutorMsgBodyStatus,
        RemoteExecutorMsgBodyHeartbeat,
        RemoteExecutorMsgBodyStartJob,
        RemoteExecutorMsgBodyGetLogChunks,
        RemoteExecutorMsgBodyLogChunks,
        RemoteExecutorMsgBodyGetLogChunk,
        RemoteExecutorMsgBodyLogChunkData,
        RemoteExecutorMsgBodyJobId,
    ]

    @model_validator(mode="after")
    def check_body_type(self) -> "RemoteExecutorMessage":
        type_mapping = {
            "log_message": RemoteExecutorMsgBodyLogMessage,
            "ack": RemoteExecutorMsgBodyAck,
            "finish": RemoteExecutorMsgBodyFinish,
            "status": RemoteExecutorMsgBodyStatus,
            "heartbeat": RemoteExecutorMsgBodyHeartbeat,
            "start_job": RemoteExecutorMsgBodyStartJob,
            "get_log_chunks": RemoteExecutorMsgBodyGetLogChunks,
            "log_chunks": RemoteExecutorMsgBodyLogChunks,
            "get_log_chunk": RemoteExecutorMsgBodyGetLogChunk,
            "log_chunk_data": RemoteExecutorMsgBodyLogChunkData,
            "subscribe_logs": RemoteExecutorMsgBodySubscribeLogs,
            "unsubscribe_logs": RemoteExecutorMsgBodyUnsubscribeLogs,
        }
        expected_type = type_mapping.get(self.msg_type)
        if expected_type and not isinstance(self.msg_body, expected_type):
            raise ValueError(
                f"msg_body for '{self.msg_type}' must be {expected_type.__name__}"
            )
        return self


class RemoteExecutorClient:
    def __init__(
        self,
        node_id: str,
        url: str,
        ssl_context: ssl.SSLContext,
        log_dir: str = "./logs",
        log_retention_days: int = 7,
    ):
        self.node_id = node_id
        self.url = url
        self.ssl_context = ssl_context
        self.log_dir = os.path.abspath(path=log_dir)
        self.log_retention_days = log_retention_days

        self.ws = None
        self.msg_id_counter = 0
        self.pending_acks: Dict[int, asyncio.Event] = {}

        # Persistent state
        self.busy = False
        self.current_job_id: Optional[str] = None
        self.log_buffer: List[RemoteExecutorLogEntry] = []
        self.unacked_log_batches: List[List[RemoteExecutorLogEntry]] = []

        self.running = True
        self.last_activity = time.time()
        self.heartbeat_interval = 30
        self.last_log_send = time.time()
        self._log_chunk_counter: Dict[str, int] = {}
        self._log_subscribers: Set[str] = set()
        self._disk_buffer: List[RemoteExecutorLogEntry] = []

    async def _send_message(self, msg_type: str, body: BaseModel):
        if not self.ws:
            raise ConnectionError("Not connected")

        msg_id = self.msg_id_counter
        self.msg_id_counter += 1

        msg = RemoteExecutorMessage(
            msg_id=msg_id,
            msg_type=msg_type,
            msg_body=body
        )

        ack_event = asyncio.Event()
        self.pending_acks[msg_id] = ack_event

        await self.ws.send(msg.model_dump_json())
        self.last_activity = time.time()

        try:
            await asyncio.wait_for(fut=ack_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            print(f"Timeout waiting for ACK for msg_id {msg_id}")
            raise
        finally:
            self.pending_acks.pop(msg_id, None)

    async def _send_ack(self, acked_ids: List[int]):
        if not self.ws:
            return
        msg = RemoteExecutorMessage(
            msg_type="ack",
            msg_body=RemoteExecutorMsgBodyAck(acked_ids=acked_ids)
        )
        await self.ws.send(msg.model_dump_json())
        self.last_activity = time.time()

    async def run(self):
        asyncio.create_task(coro=self._log_flusher())
        asyncio.create_task(coro=self._cleanup_logs())

        while self.running:
            print(f"Connecting to {self.url}...")
            try:
                async with websockets.connect(uri=self.url, ssl=self.ssl_context, open_timeout=10) as websocket:
                    self.ws = websocket
                    print("Connected!")
                    await self._handle_connection()
            except Exception as e:
                print(f"Connection error: {e}")
                self.ws = None
                # Wake up any pending ACKs so they can fail
                for event in self.pending_acks.values():
                    event.set()

            if self.running:
                print("Retrying in 5 seconds...")
                await asyncio.sleep(delay=5)

    async def _handle_connection(self):
        receiver_task = asyncio.create_task(coro=self._receiver())
        heartbeat_task = asyncio.create_task(coro=self._heartbeat())

        # 1. Resend unacked logs from previous sessions
        if self.unacked_log_batches:
            print(f"Resending {len(self.unacked_log_batches)} unacked log batches...")
            for batch in list(self.unacked_log_batches):
                asyncio.create_task(coro=self._send_log_batch(batch=batch, is_resend=True))

        # 2. Initial status
        try:
            await self._send_message(
                msg_type="status",
                body=RemoteExecutorMsgBodyStatus(
                    busy=self.busy, current_job_id=self.current_job_id
                ),
            )
        except Exception as e:
            print(f"Failed to send initial status: {e}")
            return

        try:
            await receiver_task
        except Exception as e:
            print(f"Receiver task error: {e}")
        finally:
            heartbeat_task.cancel()
            try:
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            except Exception:
                pass

    async def _receiver(self):
        try:
            while self.ws:
                data = await self.ws.recv()
                self.last_activity = time.time()
                await self._handle_message(data=data)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
        except Exception as e:
            print(f"Receiver error: {e}")

    async def _handle_message(self, data):
        try:
            msg = RemoteExecutorMessage.model_validate_json(json_data=data)

            if msg.msg_type == "ack":
                if isinstance(msg.msg_body, RemoteExecutorMsgBodyAck):
                    for aid in msg.msg_body.acked_ids:
                        if aid in self.pending_acks:
                            self.pending_acks[aid].set()
                return

            if msg.msg_id is not None:
                await self._send_ack(acked_ids=[msg.msg_id])

            if msg.msg_type == "start_job" and isinstance(msg.msg_body, RemoteExecutorMsgBodyStartJob):
                if self.busy:
                    print(f"Already busy, ignoring job {msg.msg_body.job_id}")
                else:
                    self.busy = True
                    self.current_job_id = msg.msg_body.job_id
                    asyncio.create_task(coro=self._run_job(job_body=msg.msg_body))
            elif msg.msg_type == "get_log_chunks" and isinstance(msg.msg_body, RemoteExecutorMsgBodyGetLogChunks):
                asyncio.create_task(coro=self._handle_get_log_chunks(body=msg.msg_body))
            elif msg.msg_type == "get_log_chunk" and isinstance(msg.msg_body, RemoteExecutorMsgBodyGetLogChunk):
                asyncio.create_task(coro=self._handle_get_log_chunk(body=msg.msg_body))
            elif msg.msg_type == "subscribe_logs" and isinstance(msg.msg_body, RemoteExecutorMsgBodySubscribeLogs):
                asyncio.create_task(coro=self._handle_subscribe_logs(body=msg.msg_body))
            elif msg.msg_type == "unsubscribe_logs" and isinstance(msg.msg_body, RemoteExecutorMsgBodyUnsubscribeLogs):
                asyncio.create_task(coro=self._handle_unsubscribe_logs(body=msg.msg_body))
            elif msg.msg_type == "heartbeat":
                pass

        except ValidationError as e:
            print(f"Validation error: {e}")
        except Exception as e:
            print(f"Error handling message: {e}")

    async def _handle_subscribe_logs(self, body: RemoteExecutorMsgBodySubscribeLogs):
        self._log_subscribers.add(body.job_id)
        print(f"Added subscriber for job {body.job_id}. Total: {len(self._log_subscribers)}")

        # 1. Send all existing chunks for this job
        chunks_dir = os.path.join(self.log_dir, body.job_id, "chunks")
        if os.path.exists(path=chunks_dir):
            chunks = sorted(
                [f for f in os.listdir(path=chunks_dir) if f.endswith(".json")]
            )
            for chunk_file in chunks:
                chunk_path = os.path.join(chunks_dir, chunk_file)
                try:
                    with open(file=chunk_path, mode="r") as f:
                        chunk_data = json.load(fp=f)
                        logs = [RemoteExecutorLogEntry(**entry) for entry in chunk_data]
                        await self._send_message(
                            msg_type="log_message",
                            body=RemoteExecutorMsgBodyLogMessage(logs=logs),
                        )
                except Exception as e:
                    print(f"Error reading chunk {chunk_path} for catch-up: {e}")

        # 2. If this is the current active job, also send what's currently in the buffers
        if self.current_job_id == body.job_id:
            # Send current disk buffer
            if self._disk_buffer:
                await self._send_message(
                    msg_type="log_message",
                    body=RemoteExecutorMsgBodyLogMessage(logs=list(self._disk_buffer)),
                )
            # Send current log_buffer (real-time pending)
            if self.log_buffer:
                await self._send_message(
                    msg_type="log_message",
                    body=RemoteExecutorMsgBodyLogMessage(logs=list(self.log_buffer)),
                )

    async def _handle_unsubscribe_logs(self, body: RemoteExecutorMsgBodyUnsubscribeLogs):
        self._log_subscribers.discard(body.job_id)
        print(f"Removed subscriber for job {body.job_id}. Total: {len(self._log_subscribers)}")

    async def _handle_get_log_chunks(self, body: RemoteExecutorMsgBodyGetLogChunks):
        chunks_dir = os.path.join(self.log_dir, body.job_id, "chunks")
        chunks = []
        if os.path.exists(path=chunks_dir):
            chunks = sorted(
                [f for f in os.listdir(path=chunks_dir) if f.endswith(".json")]
            )

        resp = RemoteExecutorMsgBodyLogChunks(
            job_id=body.job_id, request_id=body.request_id, chunks=chunks
        )
        await self._send_message(msg_type="log_chunks", body=resp)

    async def _handle_get_log_chunk(self, body: RemoteExecutorMsgBodyGetLogChunk):
        chunk_path = os.path.join(self.log_dir, body.job_id, "chunks", body.chunk_id)
        data = []
        if os.path.exists(path=chunk_path):
            try:
                with open(file=chunk_path, mode="r") as f:
                    chunk_data = json.load(fp=f)
                    data = [RemoteExecutorLogEntry(**entry) for entry in chunk_data]
            except Exception as e:
                print(f"Error reading chunk {chunk_path}: {e}")

        resp = RemoteExecutorMsgBodyLogChunkData(
            job_id=body.job_id,
            chunk_id=body.chunk_id,
            request_id=body.request_id,
            data=data,
        )
        await self._send_message(msg_type="log_chunk_data", body=resp)

    async def _cleanup_logs(self):
        while self.running:
            try:
                if not os.path.exists(path=self.log_dir):
                    await asyncio.sleep(delay=3600)
                    continue

                now = time.time()
                retention_secs = self.log_retention_days * 86400

                for job_id in os.listdir(path=self.log_dir):
                    job_path = os.path.join(self.log_dir, job_id)
                    if not os.path.isdir(s=job_path):
                        continue

                    st = os.stat(path=job_path)
                    if now - st.st_mtime > retention_secs:
                        print(f"Cleaning up old logs for job {job_id}")
                        import shutil
                        shutil.rmtree(path=job_path)
            except Exception as e:
                print(f"Error during log cleanup: {e}")

            await asyncio.sleep(delay=3600)

    async def _heartbeat(self):
        while self.ws:
            await asyncio.sleep(delay=self.heartbeat_interval)
            if time.time() - self.last_activity >= self.heartbeat_interval:
                try:
                    await self._send_message(msg_type="heartbeat", body=RemoteExecutorMsgBodyHeartbeat())
                except Exception:
                    pass

    async def _log_flusher(self):
        while self.running:
            # 1. Real-time streaming (fast as possible)
            if self.log_buffer and self.ws and self.current_job_id in self._log_subscribers:
                # We send in batches of up to 100 to avoid massive messages
                batch = self.log_buffer[:100]
                self.log_buffer = self.log_buffer[100:]
                asyncio.create_task(coro=self._send_log_batch(batch=batch))
            elif self.log_buffer and self.current_job_id not in self._log_subscribers:
                # If no one is listening, we just empty the buffer
                # because logs are already in _disk_buffer
                self.log_buffer.clear()

            # 2. Disk chunking (1000 lines)
            if len(self._disk_buffer) >= 1000:
                batch = self._disk_buffer[:1000]
                self._disk_buffer = self._disk_buffer[1000:]
                if self.current_job_id:
                    self._save_log_chunk(job_id=self.current_job_id, batch=batch)

            await asyncio.sleep(delay=0.1)

    def _save_log_chunk(self, job_id: str, batch: List[RemoteExecutorLogEntry]):
        chunks_dir = os.path.join(self.log_dir, job_id, "chunks")
        os.makedirs(name=chunks_dir, exist_ok=True)

        chunk_nr = self._log_chunk_counter.get(job_id, 0)
        self._log_chunk_counter[job_id] = chunk_nr + 1

        chunk_path = os.path.join(chunks_dir, f"chunk_{chunk_nr:05d}.json")
        try:
            with open(file=chunk_path, mode="w") as f:
                json.dump(obj=[entry.model_dump(mode="json") for entry in batch], fp=f)
        except Exception as e:
            print(f"Error saving log chunk {chunk_path}: {e}")

    async def _send_log_batch(self, batch: List[RemoteExecutorLogEntry], is_resend: bool = False):
        if not is_resend:
            self.unacked_log_batches.append(batch)

        while self.running:
            try:
                await self._send_message(msg_type="log_message", body=RemoteExecutorMsgBodyLogMessage(logs=batch))
                # If we reached here, it was ACKed
                if batch in self.unacked_log_batches:
                    self.unacked_log_batches.remove(batch)
                break
            except Exception as e:
                print(f"Failed to send log batch (resend={is_resend}): {e}")
                if not is_resend:
                    break
                else:
                    await asyncio.sleep(delay=5)

    async def _run_job(self, job_body: RemoteExecutorMsgBodyStartJob):
        print(f"Starting job {job_body.job_id}: {job_body.executable}")
        print(f"[{job_body.job_id}] Parameters: {job_body.parameters}")

        # Reset chunk counter for new job
        self._log_chunk_counter[job_body.job_id] = 0

        try:
            # Prepare command tokens safely
            args = []
            for token in job_body.params_template:
                if token.startswith("{") and token.endswith("}"):
                    key = token.strip("{}")
                    val = job_body.parameters.get(key, "")
                    args.append(str(val))
                else:
                    args.append(token)

            print(f"[{job_body.job_id}] Arguments: {args}")

            env = os.environ.copy()
            env.update(job_body.env_vars)

            process = await asyncio.create_subprocess_exec(
                job_body.executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            line_nr = 1
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode().strip()
                # print(f"[{job_body.job_id}] {line}")

                log_entry = RemoteExecutorLogEntry(
                    line_nr=line_nr, timestamp=datetime.now(), msg=line
                )
                self.log_buffer.append(log_entry)
                self._disk_buffer.append(log_entry)
                line_nr += 1

            exit_code = await process.wait()

            # 1. Flush remaining disk buffer as a final chunk (regardless of size)
            if self._disk_buffer:
                self._save_log_chunk(
                    job_id=job_body.job_id, batch=list(self._disk_buffer)
                )
                self._disk_buffer.clear()

            # 2. Wait for real-time log_buffer to be emptied by log_flusher if subscribers exist
            while self.log_buffer and job_body.job_id in self._log_subscribers:
                await asyncio.sleep(delay=0.5)

            # 3. Keep trying to send finish until successful or no longer running
            while self.running:
                try:
                    await self._send_message(
                        msg_type="finish",
                        body=RemoteExecutorMsgBodyFinish(exit_code=exit_code),
                    )
                    break
                except Exception as e:
                    print(f"Failed to send finish: {e}")
                    await asyncio.sleep(delay=5)

        except Exception as e:
            print(f"Error running job: {e}")
            while self.running:
                try:
                    await self._send_message(msg_type="finish", body=RemoteExecutorMsgBodyFinish(exit_code=1))
                    break
                except Exception:
                    await asyncio.sleep(delay=5)
        finally:
            self.busy = False
            self.current_job_id = None
            while self.running:
                try:
                    await self._send_message(msg_type="status", body=RemoteExecutorMsgBodyStatus(busy=False))
                    break
                except Exception:
                    await asyncio.sleep(delay=5)


import sys


def get_puppet_ssl_context():
    fqdn = socket.getfqdn()
    base_path = "/etc/puppetlabs/puppet/ssl"

    ca_cert = f"{base_path}/certs/ca.pem"
    client_cert = f"{base_path}/certs/{fqdn}.pem"
    client_key = f"{base_path}/private_keys/{fqdn}.pem"

    if not os.path.exists(path=ca_cert):
        print(f"Fatal: CA certificate not found at {ca_cert}")
        sys.exit(1)
    if not os.path.exists(path=client_cert):
        print(f"Fatal: Client certificate not found at {client_cert}")
        sys.exit(1)
    if not os.path.exists(path=client_key):
        print(f"Fatal: Client key not found at {client_key}")
        sys.exit(1)

    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    try:
        context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    except Exception as e:
        print(f"Fatal: Could not load client certificate/key: {e}")
        sys.exit(1)
    return context, client_cert


def get_cert_cn(cert_path):
    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()
        cert = x509.load_pem_x509_certificate(data=cert_data, backend=default_backend())
        common_names = cert.subject.get_attributes_for_oid(oid=x509.NameOID.COMMON_NAME)
        if common_names:
            return common_names[0].value
    except Exception as e:
        print(f"Fatal: Error extracting CN from certificate: {e}")
        sys.exit(1)
    print("Fatal: No CN found in certificate")
    sys.exit(1)


async def run_client(base_url):
    if not base_url.startswith("wss://"):
        if "://" in base_url:
            print(f"Fatal: Invalid protocol in URL {base_url}. Only wss:// is supported.")
            sys.exit(1)
        base_url = f"wss://{base_url}"

    print("Loading Puppet SSL certificates...")
    ssl_context, cert_path = get_puppet_ssl_context()

    node_id = get_cert_cn(cert_path=cert_path)

    print(f"Identified as node: {node_id}")
    url = base_url.rstrip("/") + f"/api/v1/ws/remote_executor/{node_id}"

    client = RemoteExecutorClient(node_id=node_id, url=url, ssl_context=ssl_context)
    await client.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Executor Client")
    parser.add_argument("url", help="Base URL or Host (e.g. puppetsrv-1:8000)")
    args = parser.parse_args()
    asyncio.run(main=run_client(base_url=args.url))
