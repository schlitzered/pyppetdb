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

import datetime
from typing import List
from typing import Literal
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti


class NodeJobGet(BaseModel):
    id: str
    job_id: str
    definition_id: str = ""
    node_id: str
    status: Literal["scheduled", "running", "success", "failed", "canceled"]
    created_by: str = ""
    created_at: datetime.datetime
    log_blobs: List[str] = []


class JobsNodeJobGetMulti(BaseModel):
    result: List[NodeJobGet]
    meta: MetaMulti
