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

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
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
    "facts_override",
    "report",
    "report.catalog_uuid",
    "report.status",
    "report.noop",
    "report.noop_pending",
    "report.corrective_change",
    "report.logs",
    "report.metrics",
    "report.resources",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "change_catalog",
    "change_facts",
    "change_last",
    "change_report",
    "report.status",
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


class NodeGet(BaseModel):
    id: Optional[StrictStr] = None
    catalog: NodeGetCatalog = None
    change_catalog: Optional[datetime] = None
    change_facts: Optional[datetime] = None
    change_last: Optional[datetime] = None
    change_report: Optional[datetime] = None
    disabled: Optional[bool] = None
    environment: str = None
    facts: Optional[Dict] = None
    report: Optional[NodeGetReport] = None
    facts_override: Optional[Dict[str, str]] = None


class NodeGetMultiMeta(MetaMulti):
    status_changed: Optional[int] = 0
    status_unchanged: Optional[int] = 0
    status_failed: Optional[int] = 0
    status_unreported: Optional[int] = 0


class NodeGetMulti(BaseModel):
    result: List[NodeGet]
    meta: NodeGetMultiMeta


class NodePut(BaseModel):
    disabled: Optional[bool] = False
    facts_override: Optional[Dict[str, str]] = None


class NodePutInternal(BaseModel):
    catalog: NodeGetCatalog = None
    change_catalog: Optional[datetime] = None
    change_facts: Optional[datetime] = None
    change_last: Optional[datetime] = None
    change_report: Optional[datetime] = None
    disabled: Optional[bool] = False
    environment: str = None
    facts: Optional[Dict] = None
    facts_override: Optional[Dict[str, str]] = None
    report: Optional[NodeGetReport] = None
    node_groups: Optional[List[str]] = None


class NodeDistinctFactValue(BaseModel):
    count: int
    value: Union[str, int, float, bool, list, datetime, None]


class NodeGetDistinctFactValues(BaseModel):
    result: List[NodeDistinctFactValue]
    meta: MetaMulti
