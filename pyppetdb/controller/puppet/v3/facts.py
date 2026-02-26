import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base
from pyppetdb.model.puppet_facts import PuppetFacts


class ControllerPuppetV3Facts(
    ControllerPuppetV3Base,
):

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
            prefix="/facts",
            tags=["puppet_v3_facts"],
        )

        self.router.add_api_route(
            "/{nodename}",
            self.put,
            methods=["PUT"],
            status_code=200,
        )

    async def put(
        self,
        request: Request,
        nodename: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        body_bytes = await request.body()
        try:
            body = await request.json()
            PuppetFacts(**body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid facts data: {str(e)}")

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/facts/{nodename}"

        try:
            response = await self._http.put(
                url=target_url,
                params={
                    "environment": environment,
                },
                headers=self._headers(request),
                content=body_bytes,
            )
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
