import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import FileResponse
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base


class ControllerPuppetV3FileContent(ControllerPuppetV3Base):

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
    ):
        await self.authorize_client_cert.require_cn(request)
        environment = request.query_params.get("environment")
        if not environment:
            raise HTTPException(status_code=400, detail="Missing environment parameter")

        codedir = Path("/etc/puppetlabs/code")
        env_modules = codedir / "environments" / environment / "modules"

        full_path = None
        base_path = None

        if mount_point == "modules":
            # URL: /puppet/v3/file_content/modules/apache/httpd.conf
            # mount_point: modules, file_path: apache/httpd.conf
            if "/" in file_path:
                module_name, rel_path = file_path.split("/", 1)
                full_path = env_modules / module_name / "files" / rel_path
                base_path = env_modules / module_name / "files"

        elif mount_point == "tasks":
            # URL: /puppet/v3/file_content/tasks/apache/init.sh
            # mount_point: tasks, file_path: apache/init.sh
            if "/" in file_path:
                module_name, rel_path = file_path.split("/", 1)
                full_path = env_modules / module_name / "tasks" / rel_path
                base_path = env_modules / module_name / "tasks"

        elif mount_point == "plugins":
            # ... (rest of plugins logic remains similar but optimized)
            for module_dir in env_modules.iterdir():
                if module_dir.is_dir():
                    candidate = module_dir / "lib" / file_path
                    if candidate.is_file():
                        full_path = candidate
                        base_path = module_dir / "lib"
                        break

        elif mount_point == "pluginfacts":
            for module_dir in env_modules.iterdir():
                if module_dir.is_dir():
                    candidate = module_dir / "facts.d" / file_path
                    if candidate.is_file():
                        full_path = candidate
                        base_path = module_dir / "facts.d"
                        break

        if full_path and base_path:
            # Security: ensure the resolved path is within the base directory
            try:
                full_path_resolved = full_path.resolve()
                full_path_resolved.relative_to(base_path.resolve())
                if full_path_resolved.is_file():
                    return FileResponse(
                        path=full_path_resolved,
                        media_type="application/octet-stream",
                    )
            except (ValueError, FileNotFoundError):
                pass

        # Proxy fallback if not found locally or unsupported mount
        self.log.info(f"File {mount_point}/{file_path} not found locally, falling back to puppet server")
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured and file not found locally"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/file_content/{mount_point}/{file_path}"

        try:
            response = await self._http.get(
                url=target_url,
                params=request.query_params,
                headers=self._headers(request),
                timeout=self.config.app.puppet.timeout,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
