import logging
import re
import typing

from pyppetdb.config import Config
from pyppetdb.crud.common import Crud
from pyppetdb.crud.mixins import ProjectionMixIn
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.hiera_key_models import HieraKeyModelGet
from pyppetdb.model.hiera_key_models import HieraKeyModelGetMulti
from pyppetdb.pyhiera import PyHiera


class CrudHieraKeyModels(Crud, ProjectionMixIn):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        pyhiera: PyHiera,
    ):
        super().__init__(config=config, log=log)
        self._pyhiera = pyhiera

    @property
    def pyhiera(self) -> PyHiera:
        return self._pyhiera

    def _build_item(
        self,
        key: str,
        model_type,
        fields: typing.Optional[list] = None,
    ) -> HieraKeyModelGet:
        model = model_type()
        schema = model.model.model_json_schema()
        schema.get("properties", {}).pop("sources", None)
        if "required" in schema:
            schema["required"] = [
                field for field in schema["required"] if field != "sources"
            ]
        if "$defs" in schema:
            schema["$defs"].pop("PyHieraModelBackendData", None)
            if not schema["$defs"]:
                schema.pop("$defs", None)
        item = HieraKeyModelGet(
            id=key,
            description=model.description,
            model=schema,
        )
        if fields:
            projection = self._projection(fields)
            if projection:
                item = HieraKeyModelGet(
                    **{k: v for k, v in item.model_dump().items() if k in projection}
                )
        return item

    def search(
        self,
        _id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> HieraKeyModelGetMulti:
        hiera = self.pyhiera.hiera
        items = []
        pattern = None
        if _id:
            try:
                pattern = re.compile(_id)
            except re.error as err:
                raise QueryParamValidationError(msg=f"invalid regex: {err}")
        for key, model_type in hiera.key_models.items():
            if pattern and not pattern.search(key):
                continue
            items.append(self._build_item(key, model_type, fields=fields))

        total = len(items)
        if sort:
            reverse = sort_order == "descending"
            items.sort(key=lambda item: getattr(item, sort), reverse=reverse)

        if isinstance(page, int) and page and limit:
            start = page * limit
            end = start + limit
            items = items[start:end]
        elif isinstance(limit, int):
            items = items[:limit]

        return HieraKeyModelGetMulti(
            **{"result": items, "meta": {"result_size": total}}
        )

    def get(
        self,
        _id: str,
        fields: typing.Optional[list] = None,
    ) -> HieraKeyModelGet:
        hiera = self.pyhiera.hiera
        try:
            model_type = hiera.key_models[_id]
        except KeyError:
            raise QueryParamValidationError(msg=f"key model {_id} not found")
        return self._build_item(_id, model_type, fields=fields)
