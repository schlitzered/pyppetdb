from typing import get_args as typing_get_args
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import StrictStr

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "ldap_group",
    "users",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal["id"]


class TeamGet(BaseModel):
    id: Optional[StrictStr] = None
    ldap_group: Optional[StrictStr] = ""
    users: Optional[List[StrictStr]] = None


class TeamGetMulti(BaseModel):
    result: List[TeamGet]
    meta: MetaMulti


class TeamPost(BaseModel):
    ldap_group: Optional[StrictStr] = ""
    users: Optional[List[StrictStr]] = []


class TeamPut(BaseModel):
    ldap_group: Optional[StrictStr] = None
    users: Optional[List[StrictStr]] = None
