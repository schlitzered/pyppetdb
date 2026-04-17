from typing import List
from typing import Literal
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti


class NodeJobGet(BaseModel):
    id: str
    job_id: str
    definition_id: str
    node_id: str
    status: Literal["scheduled", "running", "success", "failed", "canceled"]
    created_by: str
    log_blobs: List[str] = []


class JobsNodeJobGetMulti(BaseModel):
    result: List[NodeJobGet]
    meta: MetaMulti
