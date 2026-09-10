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
from datetime import UTC
from datetime import datetime

from fastapi import APIRouter
from fastapi import Request

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config

PUPPETDB_COMPAT_VERSION = "8.10.0"


class ControllerPdbMetaV1:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._config = config
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter(prefix="/v1", tags=["pdb_meta_v1"])

        self.router.add_api_route(
            "/version",
            self.version,
            response_model=None,
            methods=["GET"],
            status_code=200,
        )
        self.router.add_api_route(
            "/server-time",
            self.server_time,
            response_model=None,
            methods=["GET"],
            status_code=200,
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def config(self) -> Config:
        return self._config

    @property
    def router(self):
        return self._router

    async def version(self, request: Request):
        await self.authorize_client_cert.require_cn_trusted(request)
        return {"version": PUPPETDB_COMPAT_VERSION}

    async def server_time(self, request: Request):
        await self.authorize_client_cert.require_cn_trusted(request)
        now = datetime.now(UTC)
        return {"server_time": now.isoformat().replace("+00:00", "Z")}
