from typing import List, Optional, Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "authority_id",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "authority_id",
]

class CASpacePost(BaseModel):
    id: Optional[str] = None
    authority_id: str
    description: Optional[str] = None

class CASpaceGet(BaseModel):
    id: str
    authority_id: str
    description: Optional[str] = None

class CASpaceGetMulti(BaseModel):
    result: List[CASpaceGet]
    meta: MetaMulti
