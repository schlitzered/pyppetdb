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
from typing import get_args as typing_get_args
from typing import Dict
from typing import Union
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictStr
from pydantic import field_validator

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "catalog_cached",
    "catalog.catalog_uuid",
    "catalog.num_resources",
    "catalog.num_resources_exported",
    "change_catalog",
    "change_facts",
    "change_last",
    "change_report",
    "disabled",
    "environment",
    "facts",
    "facts_inject",
    "report",
    "report.catalog_uuid",
    "report.status",
    "report.noop",
    "report.noop_pending",
    "report.corrective_change",
    "report.logs",
    "report.metrics",
    "report.resources",
    "remote_agent.connected",
    "remote_agent.via",
    "remote_agent.current_job_id",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "change_catalog",
    "change_facts",
    "change_last",
    "change_report",
    "report.status",
    "remote_agent.connected",
    "remote_agent.via",
    "remote_agent.current_job_id",
]


class NodeGetCatalogResource(BaseModel):
    exported: bool
    type: str
    title: str
    tags: List[str]
    parameters: Dict[str, Any]


class NodeGetCatalogResources(BaseModel):
    result: List[NodeGetCatalogResource]
    meta: MetaMulti


class NodeGetCatalog(BaseModel):
    catalog_uuid: Optional[str] = None
    num_resources: Optional[int] = None
    num_resources_exported: Optional[int] = None
    resources: Optional[List[NodeGetCatalogResource]] = None
    resources_exported: Optional[List[NodeGetCatalogResource]] = None


class NodeGetReportLogs(BaseModel):
    file: str | None
    line: int | None
    level: str
    message: str
    source: str
    tags: List[str]
    time: str


class NodeGetReportMetrics(BaseModel):
    category: str
    name: str
    value: int | float


class NodeGetReportResourcesEvents(BaseModel):
    status: str
    timestamp: str
    name: str
    property: str | None
    new_value: str
    old_value: str
    corrective_change: bool
    message: str


class NodeGetReportResources(BaseModel):
    skipped: bool
    timestamp: str
    resource_type: str
    resource_title: str
    file: str | None
    line: int | None
    containment_path: List[str]
    corrective_change: bool
    events: List[NodeGetReportResourcesEvents]


class NodeGetReport(BaseModel):
    status: Optional[str] = None
    noop: Optional[bool] = None
    noop_pending: Optional[bool] = None
    corrective_change: Optional[bool] = None
    catalog_uuid: Optional[str] = None
    logs: Optional[List[NodeGetReportLogs]] = None
    metrics: Optional[List[NodeGetReportMetrics]] = None
    resources: Optional[List[NodeGetReportResources]] = None


class NodeRemoteAgent(BaseModel):
    connected: bool = False
    via: Optional[str] = None
    current_job_id: Optional[List[str]] = []

    @field_validator("current_job_id", mode="before")
    @classmethod
    def validate_current_job_id(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v


class NodeGet(BaseModel):
    id: Optional[StrictStr] = None
    catalog: NodeGetCatalog = None
    catalog_cached: Optional[bool] = None
    change_catalog: Optional[datetime] = None
    change_facts: Optional[datetime] = None
    change_last: Optional[datetime] = None
    change_report: Optional[datetime] = None
    disabled: Optional[bool] = None
    environment: Optional[str] = None
    facts: Optional[Dict] = None
    report: Optional[NodeGetReport] = None
    report_status_computed: Optional[str] = None
    facts_inject: Optional[Dict[str, str]] = None
    remote_agent: Optional[NodeRemoteAgent] = None


class NodeGetMultiMeta(MetaMulti):
    status_changed: Optional[int] = 0
    status_unchanged: Optional[int] = 0
    status_failed: Optional[int] = 0
    status_unreported: Optional[int] = 0
    status_outdated: Optional[int] = 0


class NodeGetMulti(BaseModel):
    result: List[NodeGet]
    meta: NodeGetMultiMeta


class NodePut(BaseModel):
    disabled: Optional[bool] = False
    facts_inject: Optional[Dict[str, str]] = None


class NodePutInternal(BaseModel):
    catalog: NodeGetCatalog = None
    change_catalog: Optional[datetime] = None
    change_facts: Optional[datetime] = None
    change_last: Optional[datetime] = None
    change_report: Optional[datetime] = None
    disabled: Optional[bool] = False
    environment: Optional[str] = None
    facts: Optional[Dict] = None
    facts_inject: Optional[Dict[str, str]] = None
    report: Optional[NodeGetReport] = None
    node_groups: Optional[List[str]] = None
    remote_agent: Optional[NodeRemoteAgent] = None


class NodeDistinctFactValue(BaseModel):
    count: int
    value: Union[str, int, float, bool, list, datetime, None]


class NodeGetDistinctFactValues(BaseModel):
    result: List[NodeDistinctFactValue]
    meta: MetaMulti
