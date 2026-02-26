import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3Node(ControllerPuppetV3Base):
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
        environment: str = Query(...),
        transaction_uuid: str = Query(...),
        configured_environment: str = Query(None),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/node/{certname}"

        try:
            response = await self._http.get(
                url=target_url,
                params={
                    "environment": environment,
                    "transaction_uuid": transaction_uuid,
                    "configured_environment": configured_environment,
                },
                headers=self._headers(request),
            )
            return response.json()

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
