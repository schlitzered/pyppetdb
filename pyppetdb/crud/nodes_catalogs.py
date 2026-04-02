from datetime import datetime
import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_catalogs import NodeCatalogGet
from pyppetdb.model.nodes_catalogs import NodeCatalogGetMulti
from pyppetdb.model.nodes_catalogs import NodeCatalogPostInternal


class NodesCatalogsRedactor:
    def __init__(self, log: logging.Logger, redactor: NodesSecretsRedactor):
        self.log = log
        self._redactor = redactor

    def redact(self, data: typing.Any) -> typing.Any:
        if not isinstance(data, dict):
            return data

        catalog = data.get("catalog")
        if not isinstance(catalog, dict):
            return data

        for resources_key in ["resources", "resources_exported"]:
            resources = catalog.get(resources_key)
            if isinstance(resources, typing.List):
                for resource in resources:
                    if not isinstance(resource, dict):
                        continue
                    parameters = resource.get("parameters")
                    if isinstance(parameters, dict):
                        # Redact only values in parameters, and we use the base redactor for the value
                        # Note: we don't redact the keys of the parameters here.
                        for k, v in parameters.items():
                            parameters[k] = self._redactor.redact(v)
        return data


class CrudNodesCatalogs(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        secret_manager: NodesCatalogsRedactor,
    ):
        super(CrudNodesCatalogs, self).__init__(config=config, log=log, coll=coll)
        self._secret_manager = secret_manager

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [
                ("placement", pymongo.ASCENDING),
                ("node_id", pymongo.ASCENDING),
                ("id", pymongo.ASCENDING),
                ("catalog.catalog_uuid", pymongo.ASCENDING),
            ],
            unique=True,
        )
        await self.coll.create_index([("catalog.status", pymongo.ASCENDING)])

        await self._create_ttl_index(
            field="created_no_report_ttl",
            ttl_seconds=self.config.app.main.storeHistory.catalogNoReportTtl,
            index_name="ttl_catalog_no_report",
        )

        await self._create_ttl_index(
            field="created",
            ttl_seconds=self.config.app.main.storeHistory.ttl,
            index_name="ttl_catalog_history",
        )

        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: datetime,
        node_id: str,
        payload: NodeCatalogPostInternal,
        fields: list,
        return_none: bool = False,
    ) -> NodeCatalogGet | None:
        data = payload.model_dump()
        data = self._secret_manager.redact(data)
        data["id"] = _id
        data["node_id"] = node_id

        result = await self._create(
            fields=fields, payload=data, return_none=return_none
        )
        if return_none:
            return None
        return NodeCatalogGet(**result)

    async def delete(
        self,
        _id: datetime,
        node_id: str,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> DataDelete:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        await self._delete(query=query)
        return DataDelete()

    async def delete_all_from_node(
        self, node_id: str, placement: typing.Optional[dict[str, str]] = None
    ):
        query = {
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        await self._coll.delete_many(filter=query)

    async def drop_created_no_report_ttl(
        self,
        _id: datetime,
        node_id: str,
        placement: typing.Optional[dict[str, str]] = None,
    ):
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        await self._coll.update_one(
            filter=query,
            update={"$unset": {"created_no_report_ttl": ""}},
        )

    async def get(
        self,
        _id: datetime | str,
        node_id: str,
        fields: list,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> NodeCatalogGet:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        result = await self._get(query=query, fields=fields)
        return NodeCatalogGet(**result)

    async def resource_exists(
        self,
        _id: datetime,
        node_id: str,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> ObjectId:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        return await self._resource_exists(query=query)

    async def search(
        self,
        node_id: str,
        catalog_status: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> NodeCatalogGetMulti:
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
        self._filter_re(query, "catalog.status", catalog_status)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return NodeCatalogGetMulti(**result)
