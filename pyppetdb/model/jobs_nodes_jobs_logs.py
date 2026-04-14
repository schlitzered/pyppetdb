from typing import List
from pydantic import BaseModel
from pyppetdb.model.remote_executor import RemoteExecutorLogEntry


class LogBlobGet(BaseModel):
    id: str
    data: List[RemoteExecutorLogEntry]
