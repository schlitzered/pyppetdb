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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class NodeResourceParam(BaseModel):
    n: str
    v: Any


class NodeResourcePostInternal(BaseModel):
    node_id: str
    placement: Optional[Dict[str, str]] = None
    environment: Optional[str] = None
    disabled: bool = False
    resource: str
    type: Optional[str] = None
    title: Optional[str] = None
    exported: bool = False
    tags: List[str] = []
    file: Optional[str] = None
    line: Optional[int] = None
    parameters: Dict[str, Any] = {}
    params_index: List[NodeResourceParam] = []
