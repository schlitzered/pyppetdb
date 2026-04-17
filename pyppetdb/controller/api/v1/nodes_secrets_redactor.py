import logging

from fastapi import APIRouter
from fastapi import Request
from fastapi import Query

from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactor
from pyppetdb.model.common import DataDelete
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGet
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGetMulti
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorPost


class ControllerApiV1NodesSecretsRedactor:
    def __init__(
        self,
        log: logging.Logger,
        authorize: AuthorizePyppetDB,
        crud_nodes_secrets_redactor: CrudNodesSecretsRedactor,
    ):
        self._authorize = authorize
        self._crud_nodes_secrets_redactor = crud_nodes_secrets_redactor
        self._log = log
        self._router = APIRouter(
            prefix="/nodes_secrets_redactor",
            tags=["nodes_secrets_redactor"],
        )

        self.router.add_api_route(
            "",
            self.search,
            response_model=NodesSecretsRedactorGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "",
            self.create,
            response_model=NodesSecretsRedactorGet,
            response_model_exclude_unset=True,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/{secret_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def router(self):
        return self._router

    async def create(self, request: Request, payload: NodesSecretsRedactorPost):
        await self.authorize.require_admin(request=request)
        return await self._crud_nodes_secrets_redactor.create(payload=payload)

    async def delete(self, request: Request, secret_id: str):
        await self.authorize.require_admin(request=request)
        return await self._crud_nodes_secrets_redactor.delete(_id=secret_id)

    async def search(
        self,
        request: Request,
        secret_id: str = Query(description="filter: regular_expressions", default=None),
        page: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=10, le=1000),
    ):
        await self.authorize.require_admin(request=request)
        return await self._crud_nodes_secrets_redactor.search(
            _id=secret_id,
            page=page,
            limit=limit,
        )
