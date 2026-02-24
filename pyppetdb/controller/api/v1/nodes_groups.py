import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.teams import CrudTeams

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_groups import filter_list
from pyppetdb.model.nodes_groups import filter_literal
from pyppetdb.model.nodes_groups import sort_literal
from pyppetdb.model.nodes_groups import NodeGroupGet
from pyppetdb.model.nodes_groups import NodeGroupGetMulti
from pyppetdb.model.nodes_groups import NodeGroupUpdate
from pyppetdb.model.nodes_groups import NodeGroupUpdateInternal


class ControllerApiV1NodesGroups:

    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes: CrudNodes,
        crud_nodes_groups: CrudNodesGroups,
        crud_teams: CrudTeams,
    ):
        self._authorize = authorize
        self._crud_nodes = crud_nodes
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_teams = crud_teams
        self._log = log
        self._router = APIRouter(
            prefix="/nodes_groups",
            tags=["nodes_groups"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodeGroupGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{node_group_id}",
            self.create,
            response_model=NodeGroupGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{node_group_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{node_group_id}",
            self.get,
            response_model=NodeGroupGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{node_group_id}",
            self.update,
            response_model=NodeGroupGet,
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
    def crud_nodes_groups(self):
        return self._crud_nodes_groups

    @property
    def crud_teams(self):
        return self._crud_teams

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def _upsert_data(
        self,
        node_group_id: str,
        data: NodeGroupUpdate,
    ):
        data = NodeGroupUpdateInternal(**data.model_dump())
        await self.add_nodes_from_filter(node_group=data)
        if data.teams:
            data.teams = list(set(data.teams))
            for team in data.teams:
                await self.crud_teams.resource_exists(_id=team)
        await self.crud_nodes.update_nodegroup(
            node_group_id=node_group_id, nodes=data.nodes
        )
        return NodeGroupUpdateInternal(**data.model_dump())

    async def create(
        self,
        request: Request,
        data: NodeGroupUpdate,
        node_group_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        data = await self._upsert_data(node_group_id=node_group_id, data=data)

        result = await self.crud_nodes_groups.create(
            _id=node_group_id,
            payload=data,
            fields=list(fields),
        )
        return result

    async def delete(
        self,
        request: Request,
        node_group_id: str,
    ):
        await self.authorize.require_admin(request=request)
        await self.crud_nodes.delete_node_group_from_all(node_group_id=node_group_id)
        return await self.crud_nodes_groups.delete(
            _id=node_group_id,
        )

    async def add_nodes_from_filter(
        self,
        node_group: NodeGroupGet | NodeGroupUpdateInternal,
    ):
        query = self.crud_nodes_groups.compile_filters_from_node_group(
            node_group=node_group
        )
        nodes = await self.crud_nodes.search(
            query=query,
            fields=["id"],
        )
        result = list()
        for node in nodes.result:
            result.append(node.id)
        node_group.nodes = result

    async def get(
        self,
        node_group_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        result = await self.crud_nodes_groups.get(
            _id=node_group_id, fields=list(fields)
        )
        return result

    async def search(
        self,
        request: Request,
        node_group_id: str = Query(
            description="filter: regular_expressions", default=None
        ),
        nodes: str = Query(description="filter: regular_expressions", default=None),
        teams: str = Query(description="filter: regular_expressions", default=None),
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
        await self.authorize.require_admin(request=request)
        return await self.crud_nodes_groups.search(
            _id=node_group_id,
            nodes=nodes,
            teams=teams,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        data: NodeGroupUpdate,
        node_group_id: str,
        request: Request,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        data = await self._upsert_data(node_group_id=node_group_id, data=data)
        result = await self.crud_nodes_groups.update(
            _id=node_group_id,
            payload=data,
            fields=list(fields),
        )
        return result
