import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.config import Config


class ControllerPuppetV3FileContent:

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
            prefix="/file_content",
            tags=["puppet_v3_file_content"],
        )

        self.router.add_api_route(
            "/{mount_point}/{file_path:path}",
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
        mount_point: str,
        file_path: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502,
                detail="Puppet server URL not configured"
            )

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_content/{mount_point}/{file_path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            self._log.debug(
                f"Forwarding file_content request: mount={mount_point}, "
                f"path={file_path}, environment={environment}"
            )

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
                media_type=response.headers.get("content-type", "application/octet-stream"),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding file_content request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )
