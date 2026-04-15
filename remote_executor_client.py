import asyncio
import base64
import json
import logging
import os
import random
import shlex
import socket
import ssl
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Literal
import argparse
import websockets
from pydantic import ValidationError

from cryptography import x509
from cryptography.hazmat.backends import default_backend

# We can't easily import from pyppetdb if it's not installed, 
# so we redefine the necessary parts of the protocol models here for the client.
from pydantic import BaseModel, model_validator

class RemoteExecutorLogEntry(BaseModel):
    line_nr: int
    timestamp: datetime
    msg: str

class RemoteExecutorMsgBodyLogMessage(BaseModel):
    logs: List[RemoteExecutorLogEntry]

class RemoteExecutorMsgBodyAck(BaseModel):
    acked_ids: List[int]

class RemoteExecutorMsgBodyFinish(BaseModel):
    exit_code: int

class RemoteExecutorMsgBodyStatus(BaseModel):
    busy: bool
    current_job_id: Optional[str] = None

class RemoteExecutorMsgBodyHeartbeat(BaseModel):
    pass

class RemoteExecutorMsgBodyStartJob(BaseModel):
    job_id: str
    executable: str
    user: str
    group: str
    params_template: List[str]
    parameters: Dict[str, Any]
    env_vars: Dict[str, str]

class RemoteExecutorMessage(BaseModel):
    msg_id: Optional[int] = None
    msg_type: Literal["log_message", "ack", "finish", "status", "heartbeat", "start_job"]
    msg_body: Union[
        RemoteExecutorMsgBodyLogMessage,
        RemoteExecutorMsgBodyAck,
        RemoteExecutorMsgBodyFinish,
        RemoteExecutorMsgBodyStatus,
        RemoteExecutorMsgBodyHeartbeat,
        RemoteExecutorMsgBodyStartJob,
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
        }
        expected_type = type_mapping.get(self.msg_type)
        if expected_type and not isinstance(self.msg_body, expected_type):
            raise ValueError(f"msg_body for '{self.msg_type}' must be {expected_type.__name__}")
        return self


class RemoteExecutorClient:
    def __init__(self, node_id: str, url: str, ssl_context: Optional[ssl.SSLContext], insecure: bool = False):
        self.node_id = node_id
        self.url = url
        self.ssl_context = ssl_context
        self.insecure = insecure
        
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
            await asyncio.wait_for(ack_event.wait(), timeout=10)
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
        asyncio.create_task(self._log_flusher())
        
        while self.running:
            print(f"Connecting to {self.url}...")
            try:
                current_ssl_context = None
                if self.url.startswith("wss://") and self.ssl_context:
                    current_ssl_context = self.ssl_context
                    if self.insecure:
                        current_ssl_context.check_hostname = False
                        current_ssl_context.verify_mode = ssl.CERT_NONE
                
                async with websockets.connect(self.url, ssl=current_ssl_context, open_timeout=10) as websocket:
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
                await asyncio.sleep(5)

    async def _handle_connection(self):
        receiver_task = asyncio.create_task(self._receiver())
        heartbeat_task = asyncio.create_task(self._heartbeat())

        # 1. Resend unacked logs from previous sessions
        if self.unacked_log_batches:
            print(f"Resending {len(self.unacked_log_batches)} unacked log batches...")
            for batch in list(self.unacked_log_batches):
                asyncio.create_task(self._send_log_batch(batch, is_resend=True))

        # 2. Initial status
        try:
            await self._send_message("status", RemoteExecutorMsgBodyStatus(
                busy=self.busy,
                current_job_id=self.current_job_id
            ))
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
                await self._handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
        except Exception as e:
            print(f"Receiver error: {e}")

    async def _handle_message(self, data):
        try:
            msg = RemoteExecutorMessage.model_validate_json(data)
            
            if msg.msg_type == "ack":
                if isinstance(msg.msg_body, RemoteExecutorMsgBodyAck):
                    for aid in msg.msg_body.acked_ids:
                        if aid in self.pending_acks:
                            self.pending_acks[aid].set()
                return

            if msg.msg_id is not None:
                await self._send_ack([msg.msg_id])

            if msg.msg_type == "start_job" and isinstance(msg.msg_body, RemoteExecutorMsgBodyStartJob):
                if self.busy:
                    print(f"Already busy, ignoring job {msg.msg_body.job_id}")
                else:
                    self.busy = True
                    self.current_job_id = msg.msg_body.job_id
                    asyncio.create_task(self._run_job(msg.msg_body))
            elif msg.msg_type == "heartbeat":
                pass
            
        except ValidationError as e:
            print(f"Validation error: {e}")
        except Exception as e:
            print(f"Error handling message: {e}")

    async def _heartbeat(self):
        while self.ws:
            await asyncio.sleep(self.heartbeat_interval)
            if time.time() - self.last_activity >= self.heartbeat_interval:
                try:
                    await self._send_message("heartbeat", RemoteExecutorMsgBodyHeartbeat())
                except Exception:
                    pass

    async def _log_flusher(self):
        while self.running:
            await asyncio.sleep(0.5)
            now = time.time()
            if self.log_buffer and (len(self.log_buffer) >= 100 or (now - self.last_log_send >= 5)):
                if not self.ws:
                    continue
                batch = self.log_buffer[:100]
                self.log_buffer = self.log_buffer[100:]
                self.last_log_send = now
                asyncio.create_task(self._send_log_batch(batch))

    async def _send_log_batch(self, batch: List[RemoteExecutorLogEntry], is_resend: bool = False):
        if not is_resend:
            self.unacked_log_batches.append(batch)
        
        while self.running:
            try:
                await self._send_message("log_message", RemoteExecutorMsgBodyLogMessage(logs=batch))
                # If we reached here, it was ACKed
                if batch in self.unacked_log_batches:
                    self.unacked_log_batches.remove(batch)
                break
            except Exception as e:
                print(f"Failed to send log batch (resend={is_resend}): {e}")
                if not is_resend:
                    # If it's a new batch, we keep it in unacked_log_batches and it will be resent
                    # But we break the loop here and let the next flush or reconnection handle it
                    break
                else:
                    # If it's a resend, we wait for a bit and try again as long as we are running
                    await asyncio.sleep(5)

    async def _run_job(self, job_body: RemoteExecutorMsgBodyStartJob):
        print(f"Starting job {job_body.job_id}: {job_body.executable}")
        print(f"[{job_body.job_id}] Parameters: {job_body.parameters}")
        
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
                print(f"[{job_body.job_id}] {line}")

                log_entry = RemoteExecutorLogEntry(
                    line_nr=line_nr,
                    timestamp=datetime.now(),
                    msg=line
                )
                self.log_buffer.append(log_entry)
                line_nr += 1

            exit_code = await process.wait()
            
            # Flush remaining logs before sending finish
            while self.log_buffer:
                batch = self.log_buffer[:100]
                self.log_buffer = self.log_buffer[100:]
                await self._send_log_batch(batch)

            # Keep trying to send finish until successful or no longer running
            while self.running:
                try:
                    await self._send_message("finish", RemoteExecutorMsgBodyFinish(exit_code=exit_code))
                    break
                except Exception as e:
                    print(f"Failed to send finish: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"Error running job: {e}")
            while self.running:
                try:
                    await self._send_message("finish", RemoteExecutorMsgBodyFinish(exit_code=1))
                    break
                except Exception:
                    await asyncio.sleep(5)
        finally:
            self.busy = False
            self.current_job_id = None
            while self.running:
                try:
                    await self._send_message("status", RemoteExecutorMsgBodyStatus(busy=False))
                    break
                except Exception:
                    await asyncio.sleep(5)


def get_puppet_ssl_context():
    fqdn = socket.getfqdn()
    base_path = "/etc/puppetlabs/puppet/ssl"

    ca_cert = f"{base_path}/certs/ca.pem"
    client_cert = f"{base_path}/certs/{fqdn}.pem"
    client_key = f"{base_path}/private_keys/{fqdn}.pem"

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    try:
        context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    except Exception as e:
        print(f"Warning: Could not load client certificate/key: {e}")
    return context, client_cert


def get_cert_cn(cert_path):
    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        common_names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        if common_names:
            return common_names[0].value
    except Exception as e:
        print(f"Error extracting CN from certificate: {e}")
    return None


async def run_client(base_url, insecure=False):
    if not base_url.startswith(("ws://", "wss://")):
        base_url = f"wss://{base_url}"

    print("Loading Puppet SSL certificates...")
    ssl_context, cert_path = get_puppet_ssl_context()

    node_id = get_cert_cn(cert_path)
    if not node_id:
        node_id = socket.getfqdn()

    print(f"Identified as node: {node_id}")
    url = base_url.rstrip("/") + f"/api/v1/ws/remote_executor/{node_id}"

    client = RemoteExecutorClient(node_id, url, ssl_context, insecure)
    await client.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Executor Client")
    parser.add_argument("url", help="Base URL or Host (e.g. puppetsrv-1:8000)")
    parser.add_argument("--insecure", action="store_true", help="Skip certificate verification")
    args = parser.parse_args()
    asyncio.run(run_client(args.url, args.insecure))
