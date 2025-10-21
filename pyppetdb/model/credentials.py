from typing import get_args as typing_get_args
from typing import Optional
from typing import List
from typing import Literal

from pydantic import BaseModel

from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "created",
    "description",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "created",
]


class CredentialGet(BaseModel):
    id: Optional[str] = None
    created: Optional[str] = None
    description: Optional[str] = None


class CredentialGetMulti(BaseModel):
    result: List[CredentialGet]
    meta: MetaMulti


class CredentialPost(BaseModel):
    description: str


class CredentialPostResult(CredentialGet):
    secret: str


class CredentialPut(BaseModel):
    description: str
