import logging


from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from pyppetdb.config import Config


class ControllerPuppetV3Catalog:

    def __init__(
        self,
        log: logging.Logger,
        config: Config,
    ):
        self._config = config
        self._log = log
        self._router = APIRouter(
            prefix="/catalog",
            tags=["puppet_v3_catalog"],
        )

    @property
    def config(self):
        return self._config

    @property
    def router(self):
        return self._router

    async def get(
        self,
        request: Request,
        nodename: str,
        environment: str = Query(
            description="filter: regular_expressions",
            default=None,
        ),
        facts_format: str | None = Query(
            description="most be application/json or pson",
            default=None,
        ),
        facts: dict | None = Query(
            description="serialized JSON or PSON of the facts hash. Since facts can contain &, which is also the HTTP query parameter delimiter, facts are doubly-escaped",
            default=None,
        ),
    ):
        pass
