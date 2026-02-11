import logging
from typing import Set

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyhiera.errors import PyHieraBackendError
from pyhiera.errors import PyHieraError
from pyhiera.models import PyHieraModelDataBase

from pyppetdb.authorize import Authorize
from pyppetdb.errors import QueryParamValidationError
from pydantic import constr
from pyppetdb.pyhiera import PyHiera


class ControllerApiV1HieraLookup:
    def __init__(
        self,
        log: logging.Logger,
        authorize: Authorize,
        pyhiera: PyHiera,
    ):
        self._authorize = authorize
        self._pyhiera = pyhiera
        self._log = log
        self._router = APIRouter(
            prefix="/hiera/lookup",
            tags=["hiera_lookup"],
        )

        self.router.add_api_route(
            "/{key_id}",
            self.lookup,
            response_model=PyHieraModelDataBase,
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
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    def _facts_from_query(self, fact: Set[str] | None) -> dict[str, str]:
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
        try:
            if merge:
                result = await self.pyhiera.hiera.key_data_get_merge(
                    key=key_id, facts=facts
                )
            else:
                result = await self.pyhiera.hiera.key_data_get(key=key_id, facts=facts)
            return result
        except (PyHieraError, PyHieraBackendError) as err:
            raise QueryParamValidationError(msg=str(err))
