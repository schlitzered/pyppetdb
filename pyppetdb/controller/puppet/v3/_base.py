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
        # Use a case-insensitive approach to exclude headers that must be recalculated
        exclude = {"content-length"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in exclude}
        headers["X-Client-Verify"] = "SUCCESS"
        headers["X-Client-DN"] = f"CN={node}"
        return headers
