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

import logging
from typing import List
from pyppetdb.crud.common import CrudMongo


class CrudManager:
    def __init__(self, log: logging.Logger):
        self._log = log
        self._cruds: List[CrudMongo] = []

    def register(self, crud: CrudMongo) -> CrudMongo:
        if crud not in self._cruds:
            self._cruds.append(crud)
        return crud

    async def init_all(self):
        self._log.info(f"Initializing {len(self._cruds)} CRUD components")
        for crud in self._cruds:
            self._log.debug(f"Initializing {crud.resource_type}")
            await crud.init()
        self._log.info("All CRUD components initialized successfully")
