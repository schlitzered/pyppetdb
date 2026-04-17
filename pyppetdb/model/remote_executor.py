from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, model_validator, ConfigDict
from datetime import datetime


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
                f"msg_body for '{self.msg_type}' must be {expected_type.__name__}, "
                f"got {type(self.msg_body).__name__}"
            )
        return self
