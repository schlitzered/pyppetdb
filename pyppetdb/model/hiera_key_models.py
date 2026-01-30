from typing import Any
from typing import get_args
from typing import List
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti


filter_literal = Literal[
    "id",
    "description",
    "model",
]

filter_list = set(get_args(filter_literal))

sort_literal = Literal[
    "id",
    "description",
    "model",
]


class HieraKeyModelGet(BaseModel):
    id: Optional[StrictStr] = None
    description: Optional[StrictStr] = None
    model: Optional[Any] = None


class HieraKeyModelGetMulti(BaseModel):
    result: List[HieraKeyModelGet]
    meta: MetaMulti
