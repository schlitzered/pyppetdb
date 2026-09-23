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
from typing import Optional

from pydantic import BaseModel


class NodeEventPostInternal(BaseModel):
    node_id: str
    placement: Optional[Dict[str, str]] = None
    disabled: bool = False
    created: datetime
    report_id: datetime
    report_hash: Optional[str] = None
    latest: bool = True
    run_start_time: Optional[datetime] = None
    run_end_time: Optional[datetime] = None
    environment: Optional[str] = None
    configuration_version: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[datetime] = None
    resource_type: Optional[str] = None
    resource_title: Optional[str] = None
    property: Optional[str] = None
    name: Optional[str] = None
    new_value: Any = None
    old_value: Any = None
    message: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    containment_path: List[str] = []
    containing_class: Optional[str] = None
    corrective_change: Optional[bool] = None
