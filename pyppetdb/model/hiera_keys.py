from typing import get_args as typing_get_args
from typing import List
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import StrictBool
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "key_model_id",
    "description",
    "deprecated",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "key_model_id",
    "description",
    "deprecated",
]


class HieraKeyGet(BaseModel):
    id: Optional[StrictStr] = None
    key_model_id: Optional[StrictStr] = None
    description: Optional[StrictStr] = None
    deprecated: Optional[StrictBool] = None


class HieraKeyGetMulti(BaseModel):
    result: List[HieraKeyGet]
    meta: MetaMulti


class HieraKeyPost(BaseModel):
    key_model_id: StrictStr
    description: Optional[StrictStr] = None
    deprecated: Optional[StrictBool] = False


class HieraKeyPut(BaseModel):
    key_model_id: Optional[StrictStr] = None
    description: Optional[StrictStr] = None
    deprecated: Optional[StrictBool] = None
