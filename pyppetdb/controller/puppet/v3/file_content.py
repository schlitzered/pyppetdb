import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi.responses import FileResponse
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
        codedir = Path("/etc/puppetlabs/code")
        env_modules = codedir / "environments" / environment / "modules"

        if mount_point.startswith("modules/"):
            # modules/<MODULE> mount: accesses files/ subdirectory of the module
            # URL: /puppet/v3/file_content/modules/apache/httpd.conf
            # Maps to: $codedir/environments/{env}/modules/apache/files/httpd.conf
            module_name = mount_point.split("/", 1)[1]
            full_path = env_modules / module_name / "files" / file_path
            base_path = env_modules / module_name / "files"

        elif mount_point.startswith("tasks/"):
            # tasks/<MODULE> mount: accesses tasks/ subdirectory of the module
            # URL: /puppet/v3/file_content/tasks/apache/init.sh
            # Maps to: $codedir/environments/{env}/modules/apache/tasks/init.sh
            module_name = mount_point.split("/", 1)[1]
            full_path = env_modules / module_name / "tasks" / file_path
            base_path = env_modules / module_name / "tasks"

        elif mount_point == "plugins":
            # plugins mount: magical mount that merges lib/ from all modules
            # Searches through all modules for lib/{file_path}
            # URL: /puppet/v3/file_content/plugins/facter/my_fact.rb
            full_path = None
            for module_dir in env_modules.iterdir():
                if module_dir.is_dir():
                    candidate = module_dir / "lib" / file_path
                    if candidate.is_file():
                        full_path = candidate
                        base_path = module_dir / "lib"
                        break

            if not full_path:
                raise HTTPException(
                    status_code=404,
                    detail="File not found in any module's lib directory",
                )

        elif mount_point == "pluginfacts":
            # pluginfacts mount: magical mount that merges facts.d/ from all modules
            # Searches through all modules for facts.d/{file_path}
            # URL: /puppet/v3/file_content/pluginfacts/my_fact.sh
            full_path = None
            for module_dir in env_modules.iterdir():
                if module_dir.is_dir():
                    candidate = module_dir / "facts.d" / file_path
                    if candidate.is_file():
                        full_path = candidate
                        base_path = module_dir / "facts.d"
                        break

            if not full_path:
                raise HTTPException(
                    status_code=404,
                    detail="File not found in any module's facts.d directory",
                )

        else:
            # Could be custom mount from fileserver.conf - not supported yet
            raise HTTPException(
                status_code=400, detail=f"Unsupported mount point: {mount_point}"
            )

        # Security: ensure the resolved path is within the base directory
        try:
            full_path = full_path.resolve()
            full_path.relative_to(base_path.resolve())
        except ValueError:
            raise HTTPException(
                status_code=403, detail="Access denied: path traversal detected"
            )

        # Check if file exists
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=full_path,
            media_type="application/octet-stream",
        )
