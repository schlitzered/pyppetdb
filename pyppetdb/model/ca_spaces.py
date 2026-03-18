from typing import List
from typing import Optional
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "authority_id",
    "description",
    "authority_id_history",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "authority_id",
]

class CASpacePost(BaseModel):
    authority_id: str
    description: Optional[str] = None

class CASpaceGet(BaseModel):
    id: str
    authority_id: str
    authority_id_history: List[str] = []
    description: Optional[str] = None

class CASpaceGetMulti(BaseModel):
    result: List[CASpaceGet]
    meta: MetaMulti

class CASpacePut(BaseModel):
    authority_id: Optional[str] = None
    authority_id_history: Optional[List[str]] = None
    description: Optional[str] = None
