from typing import Any

from pyhiera.models import PyHieraModelDataBase
from pyhiera.models import PyHieraModelDataString
from pyhiera.models import PyHieraModelDataInt
from pyhiera.models import PyHieraModelDataFloat
from pyhiera.models import PyHieraModelDataBool


class PyHieraKeyBase:
    def __init__(self):
        self._description = "something useful"
        self._model = PyHieraModelDataBase

    @property
    def description(self) -> str:
        return self._description

    @property
    def model(self) -> type[PyHieraModelDataBase]:
        return self._model

    def validate(self, data: Any) -> PyHieraModelDataBase:
        return self._model(data=data)


class PyHieraKeyString(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "simple string"
        self._model = PyHieraModelDataString


class PyHieraKeyInt(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "simple int"
        self._model = PyHieraModelDataInt


class PyHieraKeyFloat(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "simple float"
        self._model = PyHieraModelDataFloat


class PyHieraKeyBool(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "simple bool"
        self._model = PyHieraModelDataBool
