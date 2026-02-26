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


class ControllerPuppetV3FileBucketFile(ControllerPuppetV3Base):

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
            prefix="/file_bucket_file",
            tags=["puppet_v3_file_bucket"],
        )

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

    async def get_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}",
        )

    async def get_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
        environment: str = Query(...),
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}",
        )

    async def head_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}",
        )

    async def head_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
        environment: str = Query(...),
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}",
        )

    async def put_without_path(
        self,
        request: Request,
        md5: str,
        environment: str = Query(...),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = (
            f"{self.config.app.puppet.serverurl}/puppet/v3/file_bucket_file/md5/{md5}"
        )

        body = await request.body()

        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            response = await self._http.put(
                url=target_url,
                params={
                    "environment": environment,
                    "md5": md5,
                },
                headers=headers,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
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
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_bucket_file/md5/{md5}/{original_path}"

        body = await request.body()

        try:
            response = await self._http.put(
                url=target_url,
                params={
                    "environment": environment,
                    "md5": md5,
                    "original_path": original_path,
                },
                headers=self._headers(request),
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
