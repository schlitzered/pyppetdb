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
from pyppetdb.model.nodes_reports import NodeReportGet
from pyppetdb.model.nodes_reports import NodeReportGetMulti
from pyppetdb.model.nodes_reports import NodeReportPostInternal


class NodesReportsRedactor:
    def __init__(self, log: logging.Logger, redactor: NodesSecretsRedactor):
        self.log = log
        self._redactor = redactor

    def redact(self, data: typing.Any) -> typing.Any:
        if not isinstance(data, dict):
            return data

        report = data.get("report")
        if not isinstance(report, dict):
            return data

        # 1. report.logs: only redact "message" field of each object
        logs = report.get("logs")
        if isinstance(logs, typing.List):
            for log_entry in logs:
                if isinstance(log_entry, dict) and "message" in log_entry:
                    log_entry["message"] = self._redactor.redact(log_entry["message"])

        # 2. report.resources.[].events.[].new_value, old_value, message
        resources = report.get("resources")
        if isinstance(resources, typing.List):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                events = resource.get("events")
                if isinstance(events, typing.List):
                    for event in events:
                        if not isinstance(event, dict):
                            continue
                        for field in ["new_value", "old_value", "message"]:
                            if field in event:
                                event[field] = self._redactor.redact(event[field])

        return data


class CrudNodesReports(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        secret_manager: NodesReportsRedactor,
    ):
        super(CrudNodesReports, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._secret_manager = secret_manager

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
        data = self._secret_manager.redact(data)
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

    async def get(
        self,
        _id: datetime,
        node_id: str,
        fields: list,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> NodeReportGet:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        result = await self._get(query=query, fields=fields)
        return NodeReportGet(**result)

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
        report_catalog_uuid: typing.Optional[str] = None,
        report_status: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
        placement: typing.Optional[dict[str, str]] = None,
    ) -> NodeReportGetMulti:
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
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
