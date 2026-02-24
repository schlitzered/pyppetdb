import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.config import Config


class ControllerPuppetV3FileBucketFile:

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
            prefix="/file_bucket_file",
            tags=["puppet_v3_file_bucket"],
        )

        # Routes with optional original_path
        self.router.add_api_route(
            "/md5/{md5}",
            self.get_without_path,
            methods=["GET"],
        )

        self.router.add_api_route(
            "/md5/{md5}/{original_path:path}",
            self.get_with_path,
            methods=["GET"],
        )

        self.router.add_api_route(
            "/md5/{md5}",
            self.head_without_path,
            methods=["HEAD"],
        )

        self.router.add_api_route(
            "/md5/{md5}/{original_path:path}",
            self.head_with_path,
            methods=["HEAD"],
        )

        self.router.add_api_route(
            "/md5/{md5}",
            self.put_without_path,
            methods=["PUT"],
            status_code=200,
        )

        self.router.add_api_route(
            "/md5/{md5}/{original_path:path}",
            self.put_with_path,
            methods=["PUT"],
            status_code=200,
        )

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

    async def get_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        self._log.debug(f"GET file_bucket_file md5/{md5} environment={environment}")
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}"
        )

    async def get_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
        environment: str = Query(...),
    ):
        self._log.debug(f"GET file_bucket_file md5/{md5}/{original_path} environment={environment}")
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}"
        )

    async def head_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        self._log.debug(f"HEAD file_bucket_file md5/{md5} environment={environment}")
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}"
        )

    async def head_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
        environment: str = Query(...),
    ):
        self._log.debug(f"HEAD file_bucket_file md5/{md5}/{original_path} environment={environment}")
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}"
        )

    async def put_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502,
                detail="Puppet server URL not configured"
            )

        self._log.debug(f"PUT file_bucket_file md5/{md5} environment={environment}")

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_bucket_file/md5/{md5}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        # Get the raw body to forward
        body = await request.body()

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            # Forward the request to puppet server
            response = await self._http.put(
                url=target_url,
                headers=headers,
                content=body,
            )

            # Return the response from upstream
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding file_bucket_file request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )

    async def put_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502,
                detail="Puppet server URL not configured"
            )

        self._log.debug(f"PUT file_bucket_file md5/{md5}/{original_path} environment={environment}")

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_bucket_file/md5/{md5}/{original_path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        # Get the raw body to forward
        body = await request.body()

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            # Forward the request to puppet server
            response = await self._http.put(
                url=target_url,
                headers=headers,
                content=body,
            )

            # Return the response from upstream
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding file_bucket_file request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )
