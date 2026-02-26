import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3FileContent(ControllerPuppetV3Base):

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
            prefix="/file_content",
            tags=["puppet_v3_file_content"],
        )

        self.router.add_api_route(
            "/{mount_point}/{file_path:path}",
            self.get,
            methods=["GET"],
            status_code=200,
        )

    async def get(
        self,
        request: Request,
        mount_point: str,
        file_path: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_content/{mount_point}/{file_path}"

        try:

            response = await self._http.get(
                url=target_url,
                params={
                    "environment": environment,
                },
                headers=self._headers(request),
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "content-type": "application/octet-stream",
                },
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
