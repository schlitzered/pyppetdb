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
from pydantic import StrictInt
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "priority",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "priority",
    "description",
]


class HieraLevelGet(BaseModel):
    id: Optional[StrictStr] = None
    priority: Optional[StrictInt] = None
    description: Optional[StrictStr] = None


class HieraLevelGetMulti(BaseModel):
    result: List[HieraLevelGet]
    meta: MetaMulti


class HieraLevelPost(BaseModel):
    priority: StrictInt
    description: Optional[StrictStr] = None


class HieraLevelPut(BaseModel):
    priority: Optional[StrictInt] = None
    description: Optional[StrictStr] = None
