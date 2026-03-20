import asyncio
import json
import logging
import typing
import urllib.parse

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
import httpx

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.controller.puppet.v3._base import ControllerPuppetV3Base
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache


class ControllerPuppetV3Catalog(ControllerPuppetV3Base):

    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        http: httpx.AsyncClient,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes_catalog_cache: typing.Optional[CrudNodesCatalogCache] = None,
    ):
        super().__init__(
            config=config,
            log=log,
            http=http,
            authorize_client_cert=authorize_client_cert,
        )
        self._crud_nodes_catalog_cache = crud_nodes_catalog_cache
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
    def crud_nodes_catalog_cache(self):
        return self._crud_nodes_catalog_cache

    @staticmethod
    def _extract_nested_fact(
        facts: typing.Dict,
        fact_path: str,
    ) -> typing.Optional[str]:
        keys = fact_path.split(".")
        value = facts
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        if value is not None:
            return str(value)
        return None

    def _filter_facts(
        self,
        facts: typing.Dict,
        configured_facts: typing.List[str],
    ) -> typing.Dict[str, str]:
        filtered = {}
        for fact_path in configured_facts:
            value = self._extract_nested_fact(facts, fact_path)
            if value is not None:
                filtered[fact_path] = value
        return filtered

    async def _store_to_cache_async(
        self, node_id: str, facts: typing.Dict[str, str], catalog: typing.Any
    ):
        try:
            await self.crud_nodes_catalog_cache.upsert(
                node_id=node_id, facts=facts, catalog=catalog
            )
            self.log.debug(f"Cached catalog for node {node_id}")
        except Exception as e:
            self.log.error(f"Failed to cache catalog for node {node_id}: {e}")

    async def get(
        self,
        request: Request,
        nodename: str,
    ):
        raise HTTPException(
            status_code=405,
            detail="GET method not allowed - this endpoint is deprecated",
        )

    async def post(
        self,
        request: Request,
        nodename: str,
    ):
        await self.authorize_client_cert.require_cn_match(request, nodename)
        if self.config.app.puppet.catalogCache:
            cached_catalog = await self.crud_nodes_catalog_cache.get_catalog(
                node_id=nodename
            )
            if cached_catalog is not None:
                self.log.debug(f"Serving cached catalog for node {nodename}")
                return cached_catalog

        if not self.config.app.puppet.serverurl:
            raise HTTPException(
                status_code=502, detail="Puppet server URL not configured"
            )

        target_url = f"{self.config.app.puppet.serverurl}/puppet/v3/catalog/{nodename}"

        body = await request.form()

        try:
            response = await self._http.post(
                url=target_url,
                params=request.query_params,
                headers=self._headers(request, node=nodename),
                data=body,
            )
            catalog = response.json()
            if response.is_success and self.config.app.puppet.catalogCache:
                facts_raw = body.get("facts")
                if facts_raw:
                    try:

                        facts_str = urllib.parse.unquote(facts_raw)
                        facts_dict = json.loads(facts_str).get("values", {})

                        filtered_facts = self._filter_facts(
                            facts_dict, self.config.app.puppet.catalogCacheFacts
                        )

                        asyncio.create_task(
                            self._store_to_cache_async(
                                node_id=nodename,
                                facts=filtered_facts,
                                catalog=catalog,
                            )
                        )
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                        self.log.warning(
                            f"Failed to parse facts for caching node {nodename}: {e}"
                        )

            return catalog

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with puppet server: {str(e)}",
            )
