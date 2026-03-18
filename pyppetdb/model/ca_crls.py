from datetime import datetime
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field
from pyppetdb.model.common import MetaMulti

class CACRL(BaseModel):
    ca_id: str
    crl_pem: str
    counter: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(datetime.timezone.utc))
    next_update: datetime
    locked_at: Optional[datetime] = None

class CACRLGet(CACRL):
    pass

class CACRLGetMulti(BaseModel):
    result: List[CACRLGet]
    meta: MetaMulti
