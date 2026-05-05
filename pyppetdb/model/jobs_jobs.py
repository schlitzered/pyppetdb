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

from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti, filter_complex_search

filter_literal = Literal[
    "id",
    "definition_id",
    "created_by",
    "created_at",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "definition_id",
    "created_by",
    "created_at",
]


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
