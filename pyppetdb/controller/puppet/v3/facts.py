import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.config import Config
from pyppetdb.model.puppet_facts import PuppetFacts


class ControllerPuppetV3Facts:

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
            prefix="/facts",
            tags=["puppet_v3_facts"],
        )

        self.router.add_api_route(
            "/{nodename}",
            self.put,
            methods=["PUT"],
            status_code=200,
        )

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

    async def put(
        self,
        request: Request,
        nodename: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502,
                detail="Puppet server URL not configured"
            )

        # Validate the facts data
        body_bytes = await request.body()
        try:
            body = await request.json()
            PuppetFacts(**body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid facts data: {str(e)}")

        self._log.info(f"Facts PUT for node {nodename}, environment={environment}")

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/facts/{nodename}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            # Forward the request to puppet server
            response = await self._http.put(
                url=target_url,
                headers=headers,
                content=body_bytes,
            )

            # Return the response from upstream
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json"),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding facts request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )
