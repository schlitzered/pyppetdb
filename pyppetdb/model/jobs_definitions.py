from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti


class JobParamDefinition(BaseModel):
    type: Literal["string", "float", "bool", "int", "enum"]
    regex: Optional[str] = None
    min: Optional[Union[float, int]] = None
    max: Optional[Union[float, int]] = None
    options: Optional[List[str]] = None


class JobDefinitionGet(BaseModel):
    id: str
    executable: str
    user: str
    group: str
    params_template: List[str]
    params: Dict[str, JobParamDefinition]
    environment_variables: Dict[str, JobParamDefinition]


class JobDefinitionPost(BaseModel):
    id: str
    executable: str
    user: str
    group: str
    params_template: List[str]
    params: Dict[str, JobParamDefinition] = {}
    environment_variables: Dict[str, JobParamDefinition] = {}


class JobDefinitionPut(BaseModel):
    executable: Optional[str] = None
    user: Optional[str] = None
    group: Optional[str] = None
    params_template: Optional[List[str]] = None
    params: Optional[Dict[str, JobParamDefinition]] = None
    environment_variables: Optional[Dict[str, JobParamDefinition]] = None


class JobDefinitionGetMulti(BaseModel):
    result: List[JobDefinitionGet]
    meta: MetaMulti
