import logging


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizePuppet
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3FileMetadata(ControllerPuppetV3Base):
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
            tags=["puppet_v3_file_metadata"],
        )

        self.router.add_api_route(
            "/file_metadata/{mount_point}/{file_path:path}",
            self.get_single,
            methods=["GET"],
            status_code=200,
        )

        self.router.add_api_route(
            "/file_metadatas/{mount_point}/{file_path:path}",
            self.get_multiple,
            methods=["GET"],
            status_code=200,
        )

        self.router.add_api_route(
            "/file_metadatas/{mount_point}",
            self.get_multiple_root,
            methods=["GET"],
            status_code=200,
        )

    async def get_single(
        self,
        request: Request,
        mount_point: str,
        file_path: str,
        environment: str = Query(...),
        links: str = Query("manage"),
        checksum_type: str = Query("md5"),
        source_permissions: str = Query("ignore"),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_metadata/{mount_point}/{file_path}"

        try:

            response = await self._http.get(
                url=target_url,
                params={
                    "environment": environment,
                    "links": links,
                    "checksum_type": checksum_type,
                    "source_permissions": source_permissions,
                },
                headers=self._headers(request),
            )
            return response.json()

        except httpx.RequestError as e:
            self.log.error(
                f"Error forwarding file_metadata request to puppet server: {e}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )

    async def get_multiple(
        self,
        request: Request,
        mount_point: str,
        file_path: str,
        environment: str = Query(...),
        recurse: str = Query("no"),
        ignore: list[str] = Query(None),
        links: str = Query("manage"),
        checksum_type: str = Query("md5"),
        source_permissions: str = Query("ignore"),
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_metadatas/{mount_point}/{file_path}"

        try:

            response = await self._http.get(
                url=target_url,
                params={
                    "environment": environment,
                    "recurse": recurse,
                    "ignore": ignore,
                    "links": links,
                    "checksum_type": checksum_type,
                    "source_permissions": source_permissions,
                },
                headers=self._headers(request),
            )
            return response.json()

        except httpx.RequestError as e:
            self.log.error(
                f"Error forwarding file_metadatas request to puppet server: {e}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )

    async def get_multiple_root(
        self,
        request: Request,
        mount_point: str,
        environment: str = Query(...),
        recurse: str = Query("no"),
        ignore: list[str] = Query(None),
        links: str = Query("manage"),
        checksum_type: str = Query("md5"),
        source_permissions: str = Query("ignore"),
    ):
        self.log.info(f"GET file_metadatas for {mount_point}")
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = (
            f"{self.config.app.puppet.serverurl}/puppet/v3/file_metadatas/{mount_point}"
        )

        try:
            response = await self._http.get(
                url=target_url,
                params={
                    "recurse": recurse,
                    "ignore": ignore,
                    "links": links,
                    "checksum_type": checksum_type,
                    "environment": environment,
                    "source_permissions": source_permissions,
                },
                headers=self._headers(request),
            )
            return response.json()
        except httpx.RequestError as e:
            self.log.error(
                f"Error forwarding file_metadatas request to puppet server: {e}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
