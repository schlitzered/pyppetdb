import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.model.pyppetdb_nodes import PyppetDBNodeGet
from pyppetdb.model.pyppetdb_nodes import PyppetDBNodeGetMulti
from pyppetdb.model.pyppetdb_nodes import filter_list
from pyppetdb.model.pyppetdb_nodes import filter_literal
from pyppetdb.model.pyppetdb_nodes import sort_literal
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal


class ControllerApiV1PyppetDBNodes:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
    ):
        self._authorize = authorize
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._log = log
        self._router = APIRouter(
            prefix="/pyppetdb_nodes",
            tags=["pyppetdb_nodes"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=PyppetDBNodeGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{node_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{node_id}",
            self.get,
            response_model=PyppetDBNodeGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def router(self):
        return self._router

    async def search(
        self,
        request: Request,
        _id: str = Query(description="filter: regular_expressions", default=None),
        fields: Set[filter_literal] = Query(default=filter_list),
        sort: sort_literal = Query(default="id"),
        sort_order: sort_order_literal = Query(default="ascending"),
        page: int = Query(default=0, ge=0, description="pagination index"),
        limit: int = Query(
            default=10,
            ge=10,
            le=1000,
            description="pagination limit, min value 10, max value 1000",
        ),
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_pyppetdb_nodes.search(
            _id=_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def delete(self, request: Request, node_id: str):
        await self._authorize.require_admin(request=request)
        return await self._crud_pyppetdb_nodes.delete(_id=node_id)

    async def get(
        self,
        node_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self._authorize.require_admin(request=request)
        return await self._crud_pyppetdb_nodes.get(
            _id=node_id,
            fields=list(fields),
        )
