from typing import get_args as typing_get_args
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "filters",
    "nodes",
    "teams",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal["id"]


class NodeGroupFilterRulePart(BaseModel):
    fact: StrictStr
    values: List[StrictStr]


class NodeGroupFilterRule(BaseModel):
    part: List[NodeGroupFilterRulePart]


class NodeGroupGet(BaseModel):
    id: Optional[StrictStr] = None
    filters: Optional[List[NodeGroupFilterRule]] = None
    nodes: Optional[List[StrictStr]] = None
    teams: Optional[List[StrictStr]] = None


class NodeGroupGetMulti(BaseModel):
    result: List[NodeGroupGet]
    meta: MetaMulti


class NodeGroupUpdate(BaseModel):
    filters: Optional[List[NodeGroupFilterRule]] = None
    teams: Optional[List[StrictStr]] = None


class NodeGroupUpdateInternal(BaseModel):
    filters: Optional[List[NodeGroupFilterRule]] = None
    teams: Optional[List[StrictStr]] = None
    nodes: Optional[List[StrictStr]] = None
