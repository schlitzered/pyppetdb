from datetime import datetime
import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs

from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_catalogs import filter_list
from pyppetdb.model.nodes_catalogs import filter_literal
from pyppetdb.model.nodes_catalogs import sort_literal
from pyppetdb.model.nodes_catalogs import NodeCatalogGet
from pyppetdb.model.nodes_catalogs import NodeCatalogGetMulti


class ControllerApiV1NodesCatalogs:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
    ):
        self._authorize = authorize
        self._crud_nodes = crud_nodes
        self._crud_nodes_catalogs = crud_nodes_catalogs
        self._log = log
        self._router = APIRouter(
            prefix="/nodes/{node_id}/catalogs",
            tags=["nodes_catalogs"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodeCatalogGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{catalog_id}",
            self.get,
            response_model=NodeCatalogGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_nodes(self):
        return self._crud_nodes

    @property
    def crud_nodes_catalogs(self):
        return self._crud_nodes_catalogs

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def get(
        self,
        node_id: str,
        catalog_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        await self.crud_nodes.resource_exists(
            _id=node_id, user_node_groups=user_node_groups
        )
        return await self.crud_nodes_catalogs.get(
            _id=catalog_id,
            node_id=node_id,
            fields=list(fields),
        )

    async def search(
        self,
        request: Request,
        node_id: str,
        catalog_status: str = Query(
            description="filter: regular_expressions", default=None
        ),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="id"),
        sort_order: sort_order_literal = Query(default="descending"),
        page: int = Query(default=0, ge=0, description="pagination index"),
        limit: int = Query(
            default=10,
            ge=10,
            le=1000,
            description="pagination limit, min value 10, max value 1000",
        ),
    ):
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        await self.crud_nodes.resource_exists(
            _id=node_id, user_node_groups=user_node_groups
        )
        return await self.crud_nodes_catalogs.search(
            node_id=node_id,
            catalog_status=catalog_status,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
