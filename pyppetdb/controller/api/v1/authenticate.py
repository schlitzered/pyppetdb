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
from fastapi import Request

import httpx

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.users import CrudUsers


from pyppetdb.model.common import DataDelete
from pyppetdb.model.authenticate import AuthenticateGetUser
from pyppetdb.model.authenticate import AuthenticatePost


class ControllerApiV1Authenticate:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_users: CrudUsers,
        http: httpx.AsyncClient,
    ):
        self._authorize = authorize
        self._crud_users = crud_users
        self._http = http
        self._log = log
        self._router = APIRouter(
            prefix="/authenticate",
            tags=["authenticate"],
        )

        self.router.add_api_route(
            "", self.get, response_model=AuthenticateGetUser, methods=["GET"]
        )
        self.router.add_api_route(
            "",
            self.create,
            response_model=AuthenticateGetUser,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "", self.delete, response_model=DataDelete, methods=["DELETE"]
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_users(self):
        return self._crud_users

    @property
    def http(self):
        return self._http

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def get(self, request: Request):
        user = await self.authorize.get_user(request=request)
        return {"user": user.id}

    async def create(
        self,
        data: AuthenticatePost,
        request: Request,
    ):
        user = await self.crud_users.check_credentials(credentials=data)
        request.session["username"] = user
        return {"user": user}

    @staticmethod
    async def delete(request: Request):
        request.session.clear()
        return {}
