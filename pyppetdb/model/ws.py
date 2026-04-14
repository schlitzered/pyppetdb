from typing import List, Optional, Union, Literal
from pydantic import BaseModel, model_validator
from pyppetdb.model.remote_executor import RemoteExecutorLogEntry


class WsMsgBodyAuthenticate(BaseModel):
    token: str


class WsMsgBodyJobLogs(BaseModel):
    id: str  # job_id:node_id


class WsMsgBodyLogMessage(BaseModel):
    job_run_id: str
    logs: List[RemoteExecutorLogEntry]


class WsMsgBodyJobFinished(BaseModel):
    job_run_id: str
    status: str
    exit_code: Optional[int] = None


class WsMessage(BaseModel):
    msg_type: Literal[
        "authenticate",
        "subscribe_job_logs",
        "unsubscribe_job_logs",
        "log_message",
        "job_finished",
    ]
    msg_body: Union[
        WsMsgBodyAuthenticate,
        WsMsgBodyJobLogs,
        WsMsgBodyLogMessage,
        WsMsgBodyJobFinished,
    ]

    @model_validator(mode="after")
    def check_body_type(self) -> "WsMessage":
        type_mapping = {
            "authenticate": WsMsgBodyAuthenticate,
            "subscribe_job_logs": WsMsgBodyJobLogs,
            "unsubscribe_job_logs": WsMsgBodyJobLogs,
            "log_message": WsMsgBodyLogMessage,
            "job_finished": WsMsgBodyJobFinished,
        }
        expected_type = type_mapping.get(self.msg_type)
        if expected_type and not isinstance(self.msg_body, expected_type):
            raise ValueError(
                f"msg_body for '{self.msg_type}' must be {expected_type.__name__}, "
                f"got {type(self.msg_body).__name__}"
            )
        return self
