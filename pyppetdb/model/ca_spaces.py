from typing import List
from typing import Optional
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "ca_id",
    "ca_id_history",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "ca_id",
]


class CASpacePost(BaseModel):
    ca_id: str
    description: Optional[str] = None


class CASpaceGet(BaseModel):
    id: Optional[str] = None
    ca_id: Optional[str] = None
    ca_id_history: Optional[List[str]] = None
    description: Optional[str] = None


class CASpaceGetMulti(BaseModel):
    result: List[CASpaceGet]
    meta: MetaMulti


class CASpacePut(BaseModel):
    ca_id: Optional[str] = None
    description: Optional[str] = None
