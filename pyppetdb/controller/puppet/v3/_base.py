import logging


from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config


class ControllerPuppetV3Base:

    def __init__(
        self,
        authorize_puppet: AuthorizePuppet,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
    ):
        self._authorize_puppet = authorize_puppet
        self._config = config
        self._http = http
        self._log = log
        self._router = None

    @property
    def authorize(self) -> AuthorizePuppet:
        return self._authorize_puppet

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
        headers = dict(request.headers)
        headers["X-Client-Verify"] = "SUCCESS"
        headers["X-Client-DN"] = f"CN={node}"
        return headers
