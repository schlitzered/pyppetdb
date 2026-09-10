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

from fastapi import APIRouter

from pyppetdb.config import Config
from pyppetdb.ingest import IngestQueue
from pyppetdb.controller.pdb.meta.v1 import PUPPETDB_COMPAT_VERSION


class ControllerPdbStatus:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        ingest_queue: IngestQueue,
    ):
        self._log = log
        self._config = config
        self._ingest_queue = ingest_queue
        self._router = APIRouter(prefix="/status/v1", tags=["pdb_status"])

        self.router.add_api_route(
            "/services",
            self.services,
            response_model=None,
            methods=["GET"],
            status_code=200,
        )
        self.router.add_api_route(
            "/services/{service}",
            self.service,
            response_model=None,
            methods=["GET"],
            status_code=200,
        )

    @property
    def config(self) -> Config:
        return self._config

    @property
    def router(self):
        return self._router

    def _status(self) -> dict:
        return {
            "service_version": PUPPETDB_COMPAT_VERSION,
            "service_status_version": 1,
            "detail_level": "info",
            "state": "running",
            "status": {"write_queue": self._ingest_queue.stats},
        }

    async def services(self):
        return {
            "puppetdb-status": {
                "service_name": "puppetdb-status",
                **self._status(),
            }
        }

    async def service(self, service: str):
        return {"service_name": service, **self._status()}
