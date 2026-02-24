import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.config import Config


class ControllerPuppetV3Node:

    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
    ):
        self._config = config
        self._http = http
        self._log = log
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

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

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
                status_code=502,
                detail="Puppet server URL not configured"
            )

        self._log.info(f"Node GET for {certname}, environment={environment}, transaction_uuid={transaction_uuid}")

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/node/{certname}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            # Forward the request to puppet server
            response = await self._http.get(
                url=target_url,
                headers=headers,
            )

            # Return the response from upstream
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json"),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding node request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )
