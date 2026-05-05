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

from typing import List
from typing import Optional
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "ca_id",
    "ca_id_history",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "ca_id",
]


class CASpacePost(BaseModel):
    ca_id: str
    description: Optional[str] = None


class CASpaceGet(BaseModel):
    id: Optional[str] = None
    ca_id: Optional[str] = None
    ca_id_history: Optional[List[str]] = None
    description: Optional[str] = None


class CASpaceGetMulti(BaseModel):
    result: List[CASpaceGet]
    meta: MetaMulti


class CASpacePut(BaseModel):
    ca_id: Optional[str] = None
    description: Optional[str] = None
