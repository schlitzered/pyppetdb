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
from datetime import UTC
import logging
from typing import Optional

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor

from pyppetdb.errors import BackendError
from pyppetdb.errors import DuplicateResource

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_reports import NodeReportGet
from pyppetdb.model.nodes_reports import NodeReportGetMulti
from pyppetdb.model.nodes_reports import NodeReportPostInternal

LATEST_TRANSACTION_ATTEMPTS = 3


def report_end_time(report) -> Optional[datetime]:
    if not isinstance(report, dict):
        return None
    value = report.get("end_time")
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
                pymongo.IndexModel(
                    [("node_id", pymongo.ASCENDING)], name="idx_node_id"
                ),
                pymongo.IndexModel(
                    [("report.hash", pymongo.ASCENDING)], name="idx_report_hash"
                ),
                pymongo.IndexModel(
                    [("report.latest", pymongo.ASCENDING)], name="idx_report_latest"
                ),
                pymongo.IndexModel(
                    [("report.resources.events.status", pymongo.ASCENDING)],
                    name="idx_report_event_status",
                ),
                pymongo.IndexModel(
                    [("report.end_time", pymongo.DESCENDING)],
                    name="idx_report_end_time",
                ),
                pymongo.IndexModel(
                    [
                        ("node_id", pymongo.ASCENDING),
                        ("report.end_time", pymongo.DESCENDING),
                    ],
                    name="idx_node_id_report_end_time",
                ),
                pymongo.IndexModel(
                    [
                        ("report.latest", pymongo.ASCENDING),
                        ("report.end_time", pymongo.DESCENDING),
                    ],
                    name="idx_report_latest_end_time",
                ),
                pymongo.IndexModel(
                    [
                        ("report.environment", pymongo.ASCENDING),
                        ("report.end_time", pymongo.DESCENDING),
                    ],
                    name="idx_report_environment_end_time",
                ),
                pymongo.IndexModel(
                    [
                        ("report.status", pymongo.ASCENDING),
                        ("report.end_time", pymongo.DESCENDING),
                    ],
                    name="idx_report_status_end_time",
                ),
                pymongo.IndexModel(
                    [
                        ("node_id", pymongo.ASCENDING),
                        ("disabled", pymongo.ASCENDING),
                    ],
                    name="idx_node_id_disabled",
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

    async def set_node_disabled(self, node_id: str, disabled: bool) -> int:
        try:
            result = await self._coll.update_many(
                filter={"node_id": node_id, "disabled": {"$ne": disabled}},
                update={"$set": {"disabled": disabled}},
            )
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()
        if result.modified_count:
            self.log.info(
                f"Propagated disabled={disabled} to {result.modified_count} "
                f"stored reports of {node_id}"
            )
        return result.modified_count

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
        placement: dict[str, str],
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
        self,
        node_id: str,
        placement: dict[str, str],
    ):
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
        await self._coll.delete_many(filter=query)

    async def get(
        self,
        _id: datetime,
        node_id: str,
        placement: dict[str, str],
        fields: list,
    ) -> NodeReportGet:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        if placement:
            query["placement"] = placement
        result = await self._get(
            query=query,
            fields=fields,
        )
        return NodeReportGet(**result)

    async def resource_exists(
        self,
        _id: datetime,
        node_id: str,
        placement: dict[str, str],
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
        placement: dict[str, str],
        report_catalog_uuid: Optional[str] = None,
        report_status: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> NodeReportGetMulti:
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
        self._filter_literal(
            query=query,
            field="report.catalog_uuid",
            selector=report_catalog_uuid,
        )
        self._filter_re(
            query=query,
            field="report.status",
            selector=report_status,
        )

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return NodeReportGetMulti(**result)

    async def create_latest(
        self,
        _id: datetime,
        node_id: str,
        payload: NodeReportPostInternal,
    ) -> bool:
        data = payload.model_dump()
        data = self._secret_manager.redact(data)
        data["id"] = _id
        data["node_id"] = node_id
        data["disabled"] = False
        data["_version"] = 1
        try:
            return await self._create_latest_transactional(
                data=data,
                node_id=node_id,
            )
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateResource
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

    async def _create_latest_transactional(self, data: dict, node_id: str) -> bool:
        for attempt in range(1, LATEST_TRANSACTION_ATTEMPTS + 1):
            try:
                async with await self.coll.database.client.start_session() as session:
                    try:
                        async with session.start_transaction():
                            return await self._create_latest_base(
                                data=data,
                                node_id=node_id,
                                session=session,
                            )
                    except pymongo.errors.OperationFailure as err:
                        if err.code == 20:
                            self.log.debug(
                                f"Transactions not supported for {self.resource_type}, storing report without"
                            )
                            break
                        if attempt == LATEST_TRANSACTION_ATTEMPTS:
                            raise
                        if not err.has_error_label("TransientTransactionError"):
                            raise
                        self.log.warning(
                            f"Retrying report insert for {node_id} after transient error: {err}"
                        )
            except pymongo.errors.ConfigurationError:
                self.log.debug(
                    f"Sessions not supported for {self.resource_type}, storing report without"
                )
                break
        return await self._create_latest_base(data=data, node_id=node_id)

    async def _create_latest_base(
        self,
        data: dict,
        node_id: str,
        session: Optional[AsyncIOMotorClientSession] = None,
    ) -> bool:
        stored = await self.coll.find_one(
            filter={"node_id": node_id, "report.latest": True},
            projection={"report.end_time": 1},
            sort=[("report.end_time", pymongo.DESCENDING)],
            session=session,
        )
        stored_end_time = report_end_time((stored or {}).get("report"))
        end_time = report_end_time(data.get("report"))
        latest = (
            stored_end_time is None or end_time is None or end_time >= stored_end_time
        )
        if isinstance(data.get("report"), dict):
            data["report"]["latest"] = latest
        if latest:
            await self.coll.update_many(
                filter={"node_id": node_id, "report.latest": True},
                update={"$set": {"report.latest": False}},
                session=session,
            )
        await self.coll.insert_one(data, session=session)
        return latest

    async def update_placement(
        self,
        node_id: str,
        placement: dict[str, str],
    ):
        await self._coll.update_many(
            filter={"node_id": node_id},
            update={"$set": {"placement": placement}},
        )
