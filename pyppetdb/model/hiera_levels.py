from typing import get_args as typing_get_args
from typing import List
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "priority",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "priority",
    "description",
]


class HieraLevelGet(BaseModel):
    id: Optional[StrictStr] = None
    priority: Optional[StrictStr] = None
    description: Optional[StrictStr] = None


class HieraLevelGetMulti(BaseModel):
    result: List[HieraLevelGet]
    meta: MetaMulti


class HieraLevelPost(BaseModel):
    priority: Optional[StrictStr] = None
    description: Optional[StrictStr] = None


class HieraLevelPut(BaseModel):
    priority: Optional[StrictStr] = None
    description: Optional[StrictStr] = None
