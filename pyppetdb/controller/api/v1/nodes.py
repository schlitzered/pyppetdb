import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.teams import CrudTeams

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import filter_complex_search
from pyppetdb.model.nodes import filter_list
from pyppetdb.model.nodes import filter_literal
from pyppetdb.model.nodes import sort_literal
from pyppetdb.model.nodes import NodeGet
from pyppetdb.model.nodes import NodeGetMulti
from pyppetdb.model.nodes import NodePut
from pyppetdb.model.nodes import NodePutInternal
from pyppetdb.model.nodes import NodeGetDistinctFactValues
from pyppetdb.model.nodes import NodeGetCatalogResources


class ControllerApiV1Nodes:

    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_credentials: CrudCredentials,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_teams: CrudTeams,
    ):
        self._authorize = authorize
        self._crud_nodes = crud_nodes
        self._crud_nodes_catalogs = crud_nodes_catalogs
        self._crud_nodes_credentials = crud_nodes_credentials
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_nodes_reports = crud_nodes_reports
        self._crud_teams = crud_teams
        self._log = log
        self._router = APIRouter(
            prefix="/nodes",
            tags=["nodes"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodeGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/_distinct_fact_values",
            self.distinct_fact_values,
            response_model=NodeGetDistinctFactValues,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/_exported_resources",
            self.exported_resources,
            response_model=NodeGetCatalogResources,
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
            response_model=NodeGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{node_id}",
            self.update,
            response_model=NodeGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
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
    def crud_nodes_credentials(self):
        return self._crud_nodes_credentials

    @property
    def crud_nodes_groups(self):
        return self._crud_nodes_groups

    @property
    def crud_nodes_reports(self):
        return self._crud_nodes_reports

    @property
    def crud_teams(self):
        return self._crud_teams

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def delete(self, request: Request, node_id: str):
        await self.authorize.require_admin(request=request)
        await self.crud_nodes_credentials.delete_all_from_owner(owner=node_id)
        await self.crud_nodes_groups.delete_node_from_nodes_groups(node_id=node_id)
        await self.crud_nodes_catalogs.delete_all_from_node(node_id=node_id)
        await self.crud_nodes_reports.delete_all_from_node(node_id=node_id)
        return await self.crud_nodes.delete(_id=node_id)

    async def get(
        self,
        node_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        return await self.crud_nodes.get(
            _id=node_id,
            user_node_groups=user_node_groups,
            fields=list(fields),
        )

    async def distinct_fact_values(
        self,
        request: Request,
        fact_id: str = Query(description="fact id", default=None),
        disabled: bool = Query(default=None),
        environment: str = Query(default=None),
        fact: filter_complex_search = Query(default=None),
        report_status: str = Query(default=None),
    ):
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        return await self.crud_nodes.distinct_fact_values(
            user_node_groups=user_node_groups,
            fact_id=fact_id,
            disabled=disabled,
            environment=environment,
            fact=fact,
            report_status=report_status,
        )

    async def exported_resources(
        self,
        request: Request,
        resource_type: str = Query(),
        resource_title: str = Query(default=None),
        resource_tags: list[str] = Query(default=None),
        disabled: bool = Query(default=None),
        environment: str = Query(default=None),
        fact: filter_complex_search = Query(default=None),
    ):
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        return await self.crud_nodes.exported_resources(
            user_node_groups=user_node_groups,
            resource_type=resource_type,
            resource_title=resource_title,
            resource_tags=resource_tags,
            disabled=disabled,
            environment=environment,
            fact=fact,
        )

    async def search(
        self,
        request: Request,
        node_id: str = Query(description="filter: regular_expressions", default=None),
        disabled: bool = Query(default=None),
        environment: str = Query(
            description="filter: regular_expressions", default=None
        ),
        fact: filter_complex_search = Query(default=None),
        report_status: str = Query(
            description="filter: regular_expressions", default=None
        ),
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
        user = await self.authorize.require_user(request=request)
        user_node_groups = await self.authorize.get_user_node_groups(
            request=request, user=user
        )
        return await self.crud_nodes.search(
            _id=node_id,
            user_node_groups=user_node_groups,
            disabled=disabled,
            environment=environment,
            fact=fact,
            report_status=report_status,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        data: NodePut,
        node_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        data = NodePutInternal(**data.model_dump())

        return await self.crud_nodes.update(
            _id=node_id, payload=data, fields=list(fields)
        )
