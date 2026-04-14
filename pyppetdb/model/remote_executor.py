from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, model_validator
from datetime import datetime


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
    msg_type: Literal[
        "log_message", "ack", "finish", "status", "heartbeat", "start_job"
    ]
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
            raise ValueError(
                f"msg_body for '{self.msg_type}' must be {expected_type.__name__}, "
                f"got {type(self.msg_body).__name__}"
            )
        return self
