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
from typing import List
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo


class CrudNodesResources(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodesResources, self).__init__(config=config, log=log, coll=coll)
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("node_id", pymongo.ASCENDING)], name="idx_node_id"
                ),
                pymongo.IndexModel(
                    [("type", pymongo.ASCENDING)], name="idx_type"
                ),
                pymongo.IndexModel(
                    [("title", pymongo.ASCENDING)], name="idx_title"
                ),
                pymongo.IndexModel(
                    [("type", pymongo.ASCENDING), ("title", pymongo.ASCENDING)],
                    name="idx_type_title",
                ),
                pymongo.IndexModel(
                    [
                        ("params_index.n", pymongo.ASCENDING),
                        ("params_index.v", pymongo.ASCENDING),
                    ],
                    name="idx_params_index",
                ),
            ]
        )

    async def replace_for_node(
        self,
        node_id: str,
        placement: Optional[dict],
        docs: List[dict],
    ) -> None:
        query = {"node_id": node_id}
        if placement:
            query["placement"] = placement
        await self._coll.delete_many(filter=query)
        if docs:
            await self._coll.insert_many(docs, ordered=False)

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
