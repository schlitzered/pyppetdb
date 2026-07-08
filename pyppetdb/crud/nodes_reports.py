# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
import logging
from typing import Optional

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

    def redact(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return data

        report = data.get("report")
        if not isinstance(report, dict):
            return data

        logs = report.get("logs")
        if isinstance(logs, list):
            for log_entry in logs:
                if isinstance(log_entry, dict) and "message" in log_entry:
                    log_entry["message"] = self._redactor.redact(log_entry["message"])

        resources = report.get("resources")
        if isinstance(resources, list):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                events = resource.get("events")
                if isinstance(events, list):
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
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [
                        ("placement", pymongo.ASCENDING),
                        ("node_id", pymongo.ASCENDING),
                        ("id", pymongo.ASCENDING),
                    ],
                    unique=True,
                    name="idx_placement_node_id_report_id",
                ),
                pymongo.IndexModel(
                    [("report.status", pymongo.ASCENDING)], name="idx_report_status"
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()
        await self._create_ttl_index(
            field="created",
            ttl_seconds=self.config.app.main.storeHistory.ttl,
            index_name="ttl_report_history",
        )

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

        if return_none:
            await self._create_base(payload=data)
            return None
        result = await self._create(fields=fields, payload=data)
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
        query = {"node_id": node_id}
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
        report_catalog_uuid: Optional[str] = None,
        report_status: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
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
