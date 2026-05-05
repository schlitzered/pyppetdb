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
