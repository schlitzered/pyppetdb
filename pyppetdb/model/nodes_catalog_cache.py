from datetime import datetime
from typing import Any
from typing import Dict
from typing import Literal
from typing import Optional
from typing import get_args as typing_get_args

from pydantic import BaseModel
from pydantic import StrictStr

filter_literal = Literal[
    "id",
    "facts",
    "placement",
    "cached",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal["id"]


class NodeCatalogCacheGet(BaseModel):
    id: Optional[StrictStr] = None
    facts: Optional[Dict[str, str]] = None
    placement: Optional[Dict[str, str]] = None
    cached: Optional[bool] = None


class NodeCatalogCachePutInternal(BaseModel):
    id: str
    facts: Dict[str, str]
    catalog: Any
    placement: Optional[Dict[str, str]] = None
    ttl: datetime
