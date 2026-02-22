from typing import get_args as typing_get_args
from typing import Any
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictInt
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "level_id",
    "key_id",
    "priority",
    "facts",
    "data",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "level_id",
    "key_id",
    "priority",
]


class HieraLevelDataGet(BaseModel):
    id: Optional[StrictStr] = None
    level_id: Optional[StrictStr] = None
    key_id: Optional[StrictStr] = None
    priority: Optional[StrictInt] = None
    facts: Optional[dict[str, str]] = None
    data: Optional[Any] = None


class HieraLevelDataGetMulti(BaseModel):
    result: List[HieraLevelDataGet]
    meta: MetaMulti


class HieraLevelDataPost(BaseModel):
    facts: dict[str, str] = None
    data: Any


class HieraLevelDataPut(BaseModel):
    data: Optional[Any] = None
