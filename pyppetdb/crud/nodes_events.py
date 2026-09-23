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

import logging
from datetime import datetime
from typing import List
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo


class CrudNodesEvents(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodesEvents, self).__init__(config=config, log=log, coll=coll)
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("node_id", pymongo.ASCENDING), ("timestamp", pymongo.ASCENDING)],
                    name="idx_node_id_timestamp",
                ),
                pymongo.IndexModel(
                    [("report_hash", pymongo.ASCENDING)], name="idx_report_hash"
                ),
                pymongo.IndexModel(
                    [("timestamp", pymongo.ASCENDING)], name="idx_timestamp"
                ),
                pymongo.IndexModel(
                    [("status", pymongo.ASCENDING), ("timestamp", pymongo.ASCENDING)],
                    name="idx_status_timestamp",
                ),
                pymongo.IndexModel(
                    [("latest", pymongo.ASCENDING), ("timestamp", pymongo.ASCENDING)],
                    name="idx_latest_timestamp",
                ),
                pymongo.IndexModel(
                    [
                        ("resource_type", pymongo.ASCENDING),
                        ("resource_title", pymongo.ASCENDING),
                    ],
                    name="idx_resource_type_title",
                ),
                pymongo.IndexModel(
                    [
                        ("latest", pymongo.ASCENDING),
                        ("status", pymongo.ASCENDING),
                        ("first_for_resource", pymongo.ASCENDING),
                        ("first_for_certname", pymongo.ASCENDING),
                        ("first_for_class", pymongo.ASCENDING),
                        ("node_id", pymongo.ASCENDING),
                        ("resource_type", pymongo.ASCENDING),
                        ("resource_title", pymongo.ASCENDING),
                        ("containing_class", pymongo.ASCENDING),
                    ],
                    name="idx_latest_counts",
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()
        await self._create_ttl_index(
            field="created",
            ttl_seconds=self.config.app.main.storeHistory.ttl,
            index_name="ttl_event_history",
        )

    async def insert_for_report(self, docs: List[dict]) -> None:
        if docs:
            await self._coll.insert_many(docs, ordered=False)

    async def set_latest(self, node_id: str, latest: bool) -> None:
        await self._coll.update_many(
            filter={"node_id": node_id, "latest": {"$ne": latest}},
            update={"$set": {"latest": latest}},
        )

    async def delete_for_report(self, node_id: str, report_id: datetime) -> None:
        await self._coll.delete_many(
            filter={"node_id": node_id, "report_id": report_id}
        )

    async def delete_all_from_node(
        self,
        node_id: str,
        placement: Optional[dict] = None,
    ) -> None:
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
        await self._coll.delete_many(filter=query)

    async def set_node_disabled(self, node_id: str, disabled: bool) -> None:
        await self._coll.update_many(
            filter={"node_id": node_id, "disabled": {"$ne": disabled}},
            update={"$set": {"disabled": disabled}},
        )

    async def update_placement(
        self,
        node_id: str,
        placement: dict,
    ) -> None:
        await self._coll.update_many(
            filter={"node_id": node_id},
            update={"$set": {"placement": placement}},
        )
