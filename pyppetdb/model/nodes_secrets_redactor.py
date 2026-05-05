from typing import List
from typing import Literal
from datetime import datetime
from pydantic import BaseModel

from pyppetdb.model.common import MetaMulti

sort_literal = Literal["id", "created_at"]
filter_literal = Literal["id", "created_at"]
filter_list = ["id", "created_at"]


class NodesSecretsRedactorGet(BaseModel):
    id: str
    created_at: datetime


class NodesSecretsRedactorGetInternal(NodesSecretsRedactorGet):
    value_encrypted: str


class NodesSecretsRedactorPost(BaseModel):
    value: str


class NodesSecretsRedactorGetMulti(BaseModel):
    result: List[NodesSecretsRedactorGet]
    meta: MetaMulti
