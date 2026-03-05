from typing import List
from pydantic import BaseModel

from pyppetdb.model.common import MetaMulti

class NodesSecretsRedactorGet(BaseModel):
    id: str

class NodesSecretsRedactorGetInternal(NodesSecretsRedactorGet):
    value_encrypted: str

class NodesSecretsRedactorPost(BaseModel):
    value: str

class NodesSecretsRedactorGetMulti(BaseModel):
    result: List[NodesSecretsRedactorGet]
    meta: MetaMulti
