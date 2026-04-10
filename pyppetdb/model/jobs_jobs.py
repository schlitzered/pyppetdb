from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti, filter_complex_search


class JobGet(BaseModel):
    id: str
    definition_id: str
    parameters: Dict[str, Any]
    env_vars: Dict[str, Any]
    node_filter: filter_complex_search
    nodes: List[str]
    created_by: str
    created_at: datetime


class JobPost(BaseModel):
    definition_id: str
    parameters: Dict[str, Any] = {}
    env_vars: Dict[str, Any] = {}
    node_filter: filter_complex_search


class JobGetMulti(BaseModel):
    result: List[JobGet]
    meta: MetaMulti
