import logging
import ssl

from fastapi import APIRouter
from fastapi import Request
import httpx

from pyppetdb.config import Config


class ControllerPdbQueryV4Resources:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._log = log
        self._http = None
        self._config = config
        self._router = APIRouter(
            prefix="/resources",
            tags=["pdb_query_v4_resources"],
        )

        self.router.add_api_route(
            "",
            self.get,
            response_model=None,
            response_model_exclude_unset=True,
            methods=["GET"],
            status_code=200,
        )

    @property
    def log(self):
        return self._log

    @property
    def http(self) -> httpx.AsyncClient:
        if not self._http:
            ssl_ctx = ssl.create_default_context(cafile=self.config_app_puppetdb.ca)
            ssl_ctx.load_cert_chain(
                certfile=self.config_app_puppetdb.cert,
                keyfile=self.config_app_puppetdb.key,
            )
            self._http = httpx.AsyncClient(verify=ssl_ctx)
        return self._http

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

    async def get(
        self,
        request: Request,
    ):
        if not self.config.app.puppetdb:
            return []
        resp = await self.http.get(
            url=f"{self.config.app.puppetdb.serverurl}/pdb/query/v4/resources",
            params=request.query_params,
            headers=request.headers,
        )
        return resp.json()
