import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3FileBucketFile(ControllerPuppetV3Base):

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
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}",
        )

    async def get_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}",
        )

    async def head_without_path(
        self,
        request: Request,
        md5: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}",
        )

    async def head_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(
            status_code=404,
            detail=f"Not Found: Could not find file_bucket_file md5/{md5}/{original_path}",
        )

    async def put_without_path(
        self,
        request: Request,
        md5: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(status_code=400, detail="Not Implemented")

    async def put_with_path(
        self,
        request: Request,
        md5: str,
        original_path: str,
    ):
        await self.authorize_client_cert.require_cn(request)
        raise HTTPException(status_code=400, detail="Not Implemented")
