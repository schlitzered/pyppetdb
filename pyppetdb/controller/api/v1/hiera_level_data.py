import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.authorize import Authorize

from pyppetdb.crud.hiera_key_models import CrudHieraKeyModels
from pyppetdb.crud.hiera_keys import CrudHieraKeys
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.crud.hiera_levels import CrudHieraLevels
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.pyhiera import PyHiera

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import filter_complex_search
from pyppetdb.model.hiera_level_data import filter_list
from pyppetdb.model.hiera_level_data import filter_literal
from pyppetdb.model.hiera_level_data import sort_literal
from pyppetdb.model.hiera_level_data import HieraLevelDataGet
from pyppetdb.model.hiera_level_data import HieraLevelDataGetMulti
from pyppetdb.model.hiera_level_data import HieraLevelDataPost
from pyppetdb.model.hiera_level_data import HieraLevelDataPut


class ControllerApiV1HieraLevelData:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_key_models: CrudHieraKeyModels,
        crud_hiera_keys: CrudHieraKeys,
        crud_hiera_level_data: CrudHieraLevelData,
        crud_hiera_levels: CrudHieraLevels,
        pyhiera: PyHiera,
    ):
        self._authorize = authorize
        self._crud_hiera_key_models = crud_hiera_key_models
        self._crud_hiera_keys = crud_hiera_keys
        self._crud_hiera_level_data = crud_hiera_level_data
        self._crud_hiera_levels = crud_hiera_levels
        self._pyhiera = pyhiera
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/data",
            tags=["hiera_level_data"],
        )

        self.router.add_api_route(
            "/",
            self.search,
            response_model=HieraLevelDataGetMulti,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.create,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=201,
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.delete,
            response_model=DataDelete,
            response_model_exclude_unset=True,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.get,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/{level_id}/{data_id}/{key_id}",
            self.update,
            response_model=HieraLevelDataGet,
            response_model_exclude_unset=True,
            methods=["PUT"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def crud_hiera_key_models(self):
        return self._crud_hiera_key_models

    @property
    def crud_hiera_keys(self):
        return self._crud_hiera_keys

    @property
    def crud_hiera_level_data(self):
        return self._crud_hiera_level_data

    @property
    def crud_hiera_levels(self):
        return self._crud_hiera_levels

    @property
    def pyhiera(self):
        return self._pyhiera

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    @staticmethod
    def _validate_level_and_data_id(
        level_id: str,
        data_id: str,
        facts: dict[str, str],
    ):
        if not data_id == level_id.format(**facts):
            raise QueryParamValidationError(
                msg=f"invalid data_id {data_id}, not matching expanded level_id {level_id}"
            )

    async def create(
        self,
        request: Request,
        data: HieraLevelDataPost,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        self._validate_level_and_data_id(level_id, data_id, data.facts)
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        level = await self.crud_hiera_levels.get(_id=level_id, fields=["priority"])
        self.crud_hiera_key_models.get(_id=key.key_model_id, fields=["id"])
        model_type = self.pyhiera.hiera.key_models.get(key.key_model_id)
        if not model_type:
            raise QueryParamValidationError(
                msg=f"key model {key.key_model_id} not found"
            )
        try:
            model_type().validate(data.data)
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"invalid data for key model {key.key_model_id}: {err}"
            )
        return await self.crud_hiera_level_data.create(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            priority=level.priority,
            fields=list(fields),
        )

    async def delete(
        self,
        request: Request,
        level_id: str,
        data_id: str,
        key_id: str,
    ):
        await self.authorize.require_admin(request=request)
        return await self.crud_hiera_level_data.delete(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
        )

    async def get(
        self,
        request: Request,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        level_data = await self.crud_hiera_level_data.get(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fields=list(fields),
        )
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        await self.crud_hiera_levels.get(_id=level_id, fields=["id"])
        self.crud_hiera_key_models.get(_id=key.key_model_id, fields=["id"])
        model_type = self.pyhiera.hiera.key_models.get(key.key_model_id)
        if not model_type:
            raise QueryParamValidationError(
                msg=f"key model {key.key_model_id} not found"
            )
        try:
            model_type().validate(level_data.data)
        except ValueError as err:
            raise QueryParamValidationError(
                msg=f"invalid data for key model {key.key_model_id}: {err}"
            )
        return level_data

    async def search(
        self,
        request: Request,
        level_id: str = Query(description="filter: regular_expressions", default=None),
        key_id: str = Query(description="filter: regular_expressions", default=None),
        data_id: str = Query(description="filter: regular_expressions", default=None),
        fact: filter_complex_search = Query(default=None),
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
        return await self.crud_hiera_level_data.search(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            fact=fact,
            fields=list(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )

    async def update(
        self,
        request: Request,
        data: HieraLevelDataPut,
        level_id: str,
        data_id: str,
        key_id: str,
        fields: Set[filter_literal] = Query(default=filter_list),
    ):
        await self.authorize.require_admin(request=request)
        key = await self.crud_hiera_keys.get(_id=key_id, fields=["key_model_id"])
        await self.crud_hiera_levels.get(_id=level_id, fields=["id"])
        self.crud_hiera_key_models.get(_id=key.key_model_id, fields=["id"])
        if data.data is not None:
            model_type = self.pyhiera.hiera.key_models.get(key.key_model_id)
            if not model_type:
                raise QueryParamValidationError(
                    msg=f"key model {key.key_model_id} not found"
                )
            try:
                model_type().validate(data.data)
            except ValueError as err:
                raise QueryParamValidationError(
                    msg=f"invalid data for key model {key.key_model_id}: {err}"
                )
        return await self.crud_hiera_level_data.update(
            _id=data_id,
            key_id=key_id,
            level_id=level_id,
            payload=data,
            fields=list(fields),
        )
