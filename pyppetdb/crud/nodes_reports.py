from datetime import datetime
import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_reports import NodeReportGet
from pyppetdb.model.nodes_reports import NodeReportGetMulti
from pyppetdb.model.nodes_reports import NodeReportPostInternal


class CrudNodesReports(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodesReports, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [
                ("placement", pymongo.ASCENDING),
                ("node_id", pymongo.ASCENDING),
                ("id", pymongo.ASCENDING),
            ],
            unique=True,
        )
        await self.coll.create_index([("report.status", pymongo.ASCENDING)])

        await self._create_ttl_index(
            field="id",
            ttl_seconds=self.config.app.main.storeHistory.ttl,
            index_name="ttl_report_history",
        )

        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: datetime,
        node_id: str,
        payload: NodeReportPostInternal,
        fields: list,
        return_none: bool = False,
    ) -> NodeReportGet | None:
        data = payload.model_dump()
        data["id"] = _id
        data["node_id"] = node_id

        result = await self._create(
            fields=fields, payload=data, return_none=return_none
        )
        if return_none:
            return None
        return NodeReportGet(**result)

    async def delete(
        self,
        _id: datetime,
        node_id: str,
    ) -> DataDelete:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        await self._delete(query=query)
        return DataDelete()

    async def delete_all_from_node(self, node_id: str):
        query = {
            "node_id": node_id,
        }
        await self._coll.delete_many(filter=query)

    async def get(
        self,
        _id: datetime,
        node_id: str,
        fields: list,
    ) -> NodeReportGet:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        result = await self._get(query=query, fields=fields)
        return NodeReportGet(**result)

    async def resource_exists(
        self,
        _id: datetime,
        node_id: str,
    ) -> ObjectId:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        return await self._resource_exists(query=query)

    async def search(
        self,
        node_id: str,
        report_catalog_uuid: typing.Optional[str] = None,
        report_status: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> NodeReportGetMulti:
        query = {"node_id": node_id}
        self._filter_literal(query, "report.catalog_uuid", report_catalog_uuid)
        self._filter_re(query, "report.status", report_status)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return NodeReportGetMulti(**result)
