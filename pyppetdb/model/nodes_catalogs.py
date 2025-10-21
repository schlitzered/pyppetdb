from typing import get_args as typing_get_args
from datetime import datetime
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti
from pyppetdb.model.nodes import NodeGetCatalog

filter_literal = Literal[
    "id",
    "created",
    "node_id",
    "catalog",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal["id"]


class NodeCatalogGet(BaseModel):
    id: Optional[StrictStr] = None
    created: Optional[datetime] = None
    node_id: Optional[StrictStr] = None
    catalog: Optional[NodeGetCatalog] = None


class NodeCatalogGetMulti(BaseModel):
    result: List[NodeCatalogGet]
    meta: MetaMulti


class NodeCatalogPostInternal(BaseModel):
    placement: str = None
    created: datetime = None
    created_no_report_ttl: datetime = None
    catalog: NodeGetCatalog = None
