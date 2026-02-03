from typing import Any, Optional
from pydantic import BaseModel


class PyHieraModelBackendData(BaseModel):
    identifier: str
    priority: int
    level: str
    key: str
    data: Any


class PyHieraModelDataBase(BaseModel):
    sources: Optional[list[PyHieraModelBackendData]] = None
    data: Any


class PyHieraModelDataBool(PyHieraModelDataBase):
    data: bool


class PyHieraModelDataString(PyHieraModelDataBase):
    data: str


class PyHieraModelDataInt(PyHieraModelDataBase):
    data: int


class PyHieraModelDataFloat(PyHieraModelDataBase):
    data: float
