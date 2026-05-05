# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import List, Optional, Union, Literal
from pydantic import BaseModel, model_validator
from pyppetdb.model.remote_executor import RemoteExecutorLogEntry


class WsMsgBodyAuthenticate(BaseModel):
    token: str


class WsMsgBodyJobLogs(BaseModel):
    id: str


class WsMsgBodyLogMessage(BaseModel):
    job_run_id: str
    logs: List[RemoteExecutorLogEntry]


class WsMsgBodyJobFinished(BaseModel):
    job_run_id: str
    status: str
    exit_code: Optional[int] = None


class WsMsgBodyApiGetLogChunks(BaseModel):
    job_run_id: str
    request_id: str


class WsMsgBodyApiLogChunksResponse(BaseModel):
    job_run_id: str
    request_id: str
    chunks: List[str]


class WsMsgBodyApiGetLogChunk(BaseModel):
    job_run_id: str
    chunk_id: str
    request_id: str


class WsMsgBodyApiLogChunkResponse(BaseModel):
    job_run_id: str
    request_id: str
    chunk_id: str
    data: List[RemoteExecutorLogEntry]
    status: int


class WsMessage(BaseModel):
    msg_type: Literal[
        "authenticate",
        "subscribe_job_logs",
        "unsubscribe_job_logs",
        "log_message",
        "job_finished",
        "api_get_log_chunks",
        "api_log_chunks_response",
        "api_get_log_chunk",
        "api_log_chunk_response",
    ]
    msg_body: Union[
        WsMsgBodyAuthenticate,
        WsMsgBodyJobLogs,
        WsMsgBodyLogMessage,
        WsMsgBodyJobFinished,
        WsMsgBodyApiGetLogChunk,
        WsMsgBodyApiGetLogChunks,
        WsMsgBodyApiLogChunkResponse,
        WsMsgBodyApiLogChunksResponse,
    ]

    @model_validator(mode="after")
    def check_body_type(self) -> "WsMessage":
        type_mapping = {
            "authenticate": WsMsgBodyAuthenticate,
            "subscribe_job_logs": WsMsgBodyJobLogs,
            "unsubscribe_job_logs": WsMsgBodyJobLogs,
            "log_message": WsMsgBodyLogMessage,
            "job_finished": WsMsgBodyJobFinished,
            "api_get_log_chunks": WsMsgBodyApiGetLogChunks,
            "api_log_chunks_response": WsMsgBodyApiLogChunksResponse,
            "api_get_log_chunk": WsMsgBodyApiGetLogChunk,
            "api_log_chunk_response": WsMsgBodyApiLogChunkResponse,
        }
        expected_type = type_mapping.get(self.msg_type)
        if expected_type and not isinstance(self.msg_body, expected_type):
            raise ValueError(
                f"msg_body for '{self.msg_type}' must be {expected_type.__name__}, "
                f"got {type(self.msg_body).__name__}"
            )
        return self
