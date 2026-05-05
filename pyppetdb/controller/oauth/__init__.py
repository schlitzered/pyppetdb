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

import httpx
from fastapi import APIRouter

from pyppetdb.controller.oauth.authenticate import ControllerOauthAuthenticate
from pyppetdb.crud.oauth import CrudOAuth
from pyppetdb.crud.users import CrudUsers


class ControllerOauth:
    def __init__(
        self,
        log: logging.Logger,
        crud_oauth: dict[str, CrudOAuth],
        crud_users: CrudUsers,
        http: httpx.AsyncClient,
    ):
        self._log = log
        self._router = APIRouter()

        self.router.include_router(
            ControllerOauthAuthenticate(
                log=log,
                crud_oauth=crud_oauth,
                crud_users=crud_users,
                http=http,
            ).router,
            responses={404: {"description": "Not found"}},
        )

    @property
    def router(self):
        return self._router
