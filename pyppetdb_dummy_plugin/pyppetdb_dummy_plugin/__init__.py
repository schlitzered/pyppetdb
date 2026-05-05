# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pyhiera.keys import PyHieraKeyBase
from pyhiera.models import PyHieraModelDataBase
from pydantic import BaseModel
import typing


# Pydantic models for data validation
class NetworkConfig(BaseModel):
    ip: str
    mask: str
    gateway: typing.Optional[str] = None


class ServerData(BaseModel):
    hostname: typing.Optional[str] = None
    role: typing.Optional[typing.Literal["web", "db", "app"]] = None
    cpu_cores: typing.Optional[int] = None
    memory_gb: typing.Optional[int] = None
    networks: typing.Optional[typing.List[NetworkConfig]] = None


class UserPermissions(BaseModel):
    resource: str
    action: typing.Literal["read", "write", "admin"]


class UserData(BaseModel):
    username: str
    email: str
    is_active: bool = True
    permissions: typing.List[UserPermissions]


class StoragePolicy(BaseModel):
    retention_days: int
    backup_enabled: bool
    storage_class: typing.Literal["standard", "cold", "archive"]


class StorageData(BaseModel):
    volume_name: str
    mount_point: str
    size_gb: int
    policy: StoragePolicy


# PyHiera models (Pydantic models that wrap the data and source info)
class PyHieraModelDataServer(PyHieraModelDataBase):
    data: ServerData


class PyHieraModelDataUser(PyHieraModelDataBase):
    data: UserData


class PyHieraModelDataStorage(PyHieraModelDataBase):
    data: StorageData


# PyHiera Key classes
class ServerKeyModel(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "Server configuration key model"
        self._model = PyHieraModelDataServer


class UserKeyModel(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "User account key model"
        self._model = PyHieraModelDataUser


class StorageKeyModel(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "Storage volume key model"
        self._model = PyHieraModelDataStorage


key_models: typing.Dict[str, typing.Type[PyHieraKeyBase]] = {
    "server": ServerKeyModel,
    "user": UserKeyModel,
    "storage": StorageKeyModel,
}
