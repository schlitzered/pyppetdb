import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyhiera.errors import PyHieraBackendError
from pyhiera.errors import PyHieraError
from pyppetdb.authorize import Authorize
from pyppetdb.crud.hiera_lookup_cache import CrudHieraLookupCache
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.hiera_lookup import HieraLookupResult
from pydantic import constr
from pyppetdb.pyhiera import PyHiera


class ControllerApiV1HieraLookup:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        crud_hiera_lookup_cache: CrudHieraLookupCache,
        pyhiera: PyHiera,
    ):
        self._authorize = authorize
        self._crud_hiera_lookup_cache = crud_hiera_lookup_cache
        self._pyhiera = pyhiera
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/lookup",
            tags=["hiera_lookup"],
        )

        self.router.add_api_route(
            "/{key_id}",
            self.lookup,
            response_model=HieraLookupResult,
            response_model_exclude_unset=True,
            methods=["GET"],
        )

    @property
    def authorize(self):
        return self._authorize

    @property
    def pyhiera(self):
        return self._pyhiera

    @property
    def crud_hiera_lookup_cache(self):
        return self._crud_hiera_lookup_cache

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    @staticmethod
    def _facts_from_query(fact: Set[str] | None) -> dict[str, str]:
        if not fact:
            return {}
        facts = {}
        for item in fact:
            if ":" not in item:
                raise QueryParamValidationError(msg=f"invalid fact filter: {item}")
            name, value = item.split(":", 1)
            if not name or value == "":
                raise QueryParamValidationError(msg=f"invalid fact filter: {item}")
            facts[name] = value
        return facts

    async def lookup(
        self,
        request: Request,
        key_id: str,
        merge: bool = Query(default=False),
        fact: Set[constr(pattern=r"^[^:]+:.+$")] = Query(default=None),
    ):
        await self.authorize.require_admin(request=request)
        facts = self._facts_from_query(fact)
        cached = await self.crud_hiera_lookup_cache.get_cached(
            key_id=key_id,
            facts=facts,
            merge=merge,
        )
        if cached:
            return HieraLookupResult(**cached["result"])
        try:
            if merge:
                result = await self.pyhiera.hiera.key_data_get_merge(
                    key=key_id, facts=facts, include_sources=False
                )
            else:
                result = await self.pyhiera.hiera.key_data_get(
                    key=key_id, facts=facts, include_sources=False
                )
            await self.crud_hiera_lookup_cache.set_cached(
                key_id=key_id,
                facts=facts,
                merge=merge,
                result={"data": result.model_dump(exclude={"sources"})["data"]},
            )
            return HieraLookupResult(
                data=result.model_dump(exclude={"sources"})["data"]
            )
        except (PyHieraError, PyHieraBackendError) as err:
            raise QueryParamValidationError(msg=str(err))
