from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, StrictStr


class NodeCatalogCacheGet(BaseModel):
    id: Optional[StrictStr] = None
    facts: Optional[Dict[str, str]] = None
    placement: Optional[str] = None
    cached: Optional[bool] = None


class NodeCatalogCachePutInternal(BaseModel):
    id: str
    facts: Dict[str, str]
    catalog: Any
    placement: str
    ttl: datetime
