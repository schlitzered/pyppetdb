import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import AuthorizePyppetDB

from pyppetdb.crud.credentials import CrudCredentials
from pyppetdb.crud.nodes import CrudNodes

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.credentials import filter_list
from pyppetdb.model.credentials import filter_literal
from pyppetdb.model.credentials import sort_literal
from pyppetdb.model.credentials import CredentialGet
from pyppetdb.model.credentials import CredentialGetMulti
from pyppetdb.model.credentials import CredentialPost
from pyppetdb.model.credentials import CredentialPostResult
from pyppetdb.model.credentials import CredentialPut


class ControllerApiV1NodesCredentials:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes: CrudNodes,
        crud_nodes_credentials: CrudCredentials,
    ):
        self._authorize = authorize
        self._crud_nodes = crud_nodes
        self._crud_nodes_credentials = crud_nodes_credentials
        self._log = log
        self._router = APIRouter(
            prefix="/nodes/{node_id}/credentials",
            tags=["nodes_credentials"],
        )

        self.router.add_api_route(
            "",
            self.create,
            response_model=CredentialPostResult,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "",
            self.search,
            response_model=CredentialGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{credential_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{credential_id}",
            self.get,
            response_model=CredentialGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{credential_id}",
            self.update,
            response_model=CredentialGet,
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
    def crud_nodes_credentials(self):
        return self._crud_nodes_credentials

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    async def create(
        self,
        data: CredentialPost,
        node_id: str,
        request: Request,
    ):
        await self.authorize.require_admin(request=request)
        await self.crud_nodes.resource_exists(_id=node_id)
        return await self.crud_nodes_credentials.create(
            owner=node_id,
            payload=data,
        )

    async def delete(
        self,
        node_id: str,
        credential_id: str,
        request: Request,
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_nodes_credentials.delete(
            _id=credential_id, owner=node_id
        )

    async def get(
        self,
        request: Request,
        node_id: str,
        credential_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_nodes_credentials.get(
            owner=node_id, _id=credential_id, fields=list(fields)
        )

    async def search(
        self,
        request: Request,
        node_id: str,
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
        result = await self._crud_nodes_credentials.search(
            owner=node_id,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return result

    async def update(
        self,
        request: Request,
        node_id: str,
        credential_id: str,
        data: CredentialPut,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_nodes_credentials.update(
            _id=credential_id, owner=node_id, payload=data, fields=list(fields)
        )
