from datetime import datetime
from typing import get_args as typing_get_args
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti
from pyppetdb.model.nodes import NodeGetReport

filter_literal = Literal[
    "id",
    "node_id",
    "report",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal["id", "report.status"]


class NodeReportGet(BaseModel):
    id: Optional[datetime] = None
    node_id: Optional[StrictStr] = None
    report: Optional[NodeGetReport] = None


class NodeReportGetMulti(BaseModel):
    result: List[NodeReportGet]
    meta: MetaMulti


class NodeReportPostInternal(BaseModel):
    placement: str = None
    report: Optional[NodeGetReport] = None
