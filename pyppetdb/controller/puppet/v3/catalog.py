import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3Catalog(ControllerPuppetV3Base):

    def __init__(
        self,
        authorize_puppet: AuthorizePuppet,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
    ):
        super().__init__(
            authorize_puppet=authorize_puppet,
            config=config,
            log=log,
            http=http,
        )
        self._router = APIRouter(
            prefix="/catalog",
            tags=["puppet_v3_catalog"],
        )

        self.router.add_api_route(
            "/{nodename}",
            self.get,
            methods=["GET"],
            status_code=405,
        )

        self.router.add_api_route(
            "/{nodename}",
            self.post,
            response_model=None,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=200,
        )

    async def get(
        self,
        request: Request,
        nodename: str,
    ):
        raise HTTPException(
            status_code=405,
            detail="GET method not allowed - this endpoint is deprecated",
        )

    async def post(
        self,
        request: Request,
        nodename: str,
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/catalog/{nodename}"

        body = await request.form()

        try:
            response = await self._http.post(
                url=target_url,
                params=request.query_params,
                headers=self._headers(request, node=nodename),
                data=body,
            )
            return response.json()

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
