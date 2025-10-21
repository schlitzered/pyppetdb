from datetime import datetime
import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_reports import CrudNodesReports

from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_reports import filter_list
from pyppetdb.model.nodes_reports import filter_literal
from pyppetdb.model.nodes_reports import sort_literal
from pyppetdb.model.nodes_reports import NodeReportGet
from pyppetdb.model.nodes_reports import NodeReportGetMulti


class ControllerApiV1NodesReports:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_nodes: CrudNodes,
        crud_nodes_reports: CrudNodesReports,
    ):
        self._authorize = authorize
        self._crud_nodes = crud_nodes
        self._crud_nodes_reports = crud_nodes_reports
        self._log = log
        self._router = APIRouter(
            prefix="/nodes/{node_id}/reports",
            tags=["nodes_reports"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodeReportGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{report_id}",
            self.get,
            response_model=NodeReportGet,
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
    def crud_nodes_reports(self):
        return self._crud_nodes_reports

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def get(
        self,
        node_id: str,
        report_id: datetime,
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
        return await self.crud_nodes_reports.get(
            _id=report_id,
            node_id=node_id,
            fields=list(fields),
        )

    async def search(
        self,
        request: Request,
        node_id: str,
        report_catalog_uuid: str = Query(description="filter: literal", default=None),
        report_status: str = Query(
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
        return await self.crud_nodes_reports.search(
            node_id=node_id,
            report_catalog_uuid=report_catalog_uuid,
            report_status=report_status,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
