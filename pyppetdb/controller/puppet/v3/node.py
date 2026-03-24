import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3Node(ControllerPuppetV3Base):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
        authorize_client_cert: AuthorizeClientCert,
    ):
        super().__init__(
            config=config,
            log=log,
            http=http,
            authorize_client_cert=authorize_client_cert,
        )
        self._router = APIRouter(
            prefix="/node",
            tags=["puppet_v3_node"],
        )

        self.router.add_api_route(
            "/{certname}",
            self.get,
            methods=["GET"],
            status_code=200,
        )

    async def get(
        self,
        request: Request,
        certname: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/node/{certname}"

        try:
            response = await self._http.get(
                url=target_url,
                params=request.query_params,
                headers=self._headers(request),
                timeout=self.config.app.puppet.timeout,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
