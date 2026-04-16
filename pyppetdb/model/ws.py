from typing import List, Optional, Union, Literal
from pydantic import BaseModel, model_validator, ConfigDict
from pyppetdb.model.remote_executor import RemoteExecutorLogEntry


class WsMsgBodyAuthenticate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


class WsMsgBodyJobLogs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str  # job_id:node_id


class WsMsgBodyLogMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_run_id: str
    logs: List[RemoteExecutorLogEntry]


class WsMsgBodyJobFinished(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_run_id: str
    status: str
    exit_code: Optional[int] = None


class WsMsgBodyApiGetLogChunks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_run_id: str
    request_id: str


class WsMsgBodyApiLogChunksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_run_id: str
    request_id: str
    chunks: List[str]


class WsMsgBodyApiGetLogChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_run_id: str
    chunk_id: str
    request_id: str


class WsMsgBodyApiLogChunkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
        WsMsgBodyApiGetLogChunks,
        WsMsgBodyApiLogChunksResponse,
        WsMsgBodyApiGetLogChunk,
        WsMsgBodyApiLogChunkResponse,
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
