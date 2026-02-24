import json
import logging
from urllib.parse import unquote


from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
import httpx

from pyppetdb.config import Config
from pyppetdb.model.puppet_facts import PuppetFacts


class ControllerPuppetV3Catalog:

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
            prefix="/catalog",
            tags=["puppet_v3_catalog"],
        )

        self.router.add_api_route(
            "/{nodename}",
            self.get,
            methods=["GET"],
            status_code=405,
        )

        self.router.add_api_route(
            "/{nodename}",
            self.post,
            response_model=None,
            response_model_exclude_unset=True,
            methods=["POST"],
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
        nodename: str,
    ):
        raise HTTPException(
            status_code=405,
            detail="GET method not allowed - this endpoint is deprecated"
        )

    async def post(
        self,
        request: Request,
        nodename: str,
    ):
        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502,
                detail="Puppet server URL not configured"
            )

        # Parse form data for validation
        form_data = await request.form()

        # Validate required parameters
        environment = form_data.get('environment')
        facts_format = form_data.get('facts_format')
        facts_str = form_data.get('facts')
        transaction_uuid = form_data.get('transaction_uuid')

        if not environment:
            raise HTTPException(status_code=400, detail="Missing required parameter: environment")
        if not facts_format:
            raise HTTPException(status_code=400, detail="Missing required parameter: facts_format")
        if not facts_str:
            raise HTTPException(status_code=400, detail="Missing required parameter: facts")
        if not transaction_uuid:
            raise HTTPException(status_code=400, detail="Missing required parameter: transaction_uuid")

        # Validate facts_format
        if facts_format not in ['application/json', 'pson']:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid facts_format: {facts_format}. Must be 'application/json' or 'pson'"
            )

        # Validate facts schema
        try:
            facts_decoded = unquote(facts_str)
            facts_json = json.loads(facts_decoded)
            PuppetFacts(**facts_json)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid facts JSON: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid facts data: {str(e)}")

        # Log the request
        self._log.info(f"Catalog POST for node {nodename}, environment={environment}, transaction_uuid={transaction_uuid}")

        # Build target URL
        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/catalog/{nodename}"

        # Get the raw body to forward
        body = await request.body()

        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            # Forward the request to puppet server
            response = await self._http.post(
                url=target_url,
                headers=headers,
                content=body,
            )

            # Return the response from upstream
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json"),
            )
        except httpx.RequestError as e:
            self._log.error(f"Error forwarding catalog request to puppet server: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}"
            )
