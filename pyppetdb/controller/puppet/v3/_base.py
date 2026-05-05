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


from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config


class ControllerPuppetV3Base:

    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._config = config
        self._http = http
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._router = None

    @property
    def authorize_client_cert(self) -> AuthorizeClientCert:
        return self._authorize_client_cert

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

    @property
    def log(self):
        return self._log

    @staticmethod
    def _headers(request: Request, node: str = "dummy"):
        exclude = {"content-length"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in exclude}
        headers["X-Client-Verify"] = "SUCCESS"
        headers["X-Client-DN"] = f"CN={node}"
        return headers
