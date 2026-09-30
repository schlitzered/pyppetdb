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
import socket

from fastapi import APIRouter
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.config import Config
from pyppetdb.crud.watcher import WatcherCoordinator
from pyppetdb.model.status import StatusGet


class ControllerApiV1Status:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        authorize: AuthorizePyppetDB,
        watcher_coordinator: WatcherCoordinator,
    ):
        self._authorize = authorize
        self._log = log
        self._watcher_coordinator = watcher_coordinator
        self._instance = f"{socket.getfqdn()}:{config.app.main.port}"
        self._router = APIRouter(
            prefix="/status",
            tags=["status"],
        )

        self.router.add_api_route(
            "",
            self.get,
            response_model=StatusGet,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    @property
    def watcher_coordinator(self):
        return self._watcher_coordinator

    async def get(self, request: Request):
        await self.authorize.require_user(request=request)
        watchers = self.watcher_coordinator.status()
        return StatusGet(
            instance=self._instance,
            ready=all(watcher["state"] == "ready" for watcher in watchers),
            watchers=watchers,
        )
