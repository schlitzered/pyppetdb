from datetime import datetime
from typing import List
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "heartbeat",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "heartbeat",
]


class PyppetDBNodeGet(BaseModel):
    id: str
    heartbeat: datetime


class PyppetDBNodeGetMulti(BaseModel):
    result: List[PyppetDBNodeGet]
    meta: MetaMulti
