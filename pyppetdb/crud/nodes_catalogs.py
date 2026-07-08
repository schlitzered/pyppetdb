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

from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes_catalogs import NodeCatalogGet
from pyppetdb.model.nodes_catalogs import NodeCatalogGetMulti
from pyppetdb.model.nodes_catalogs import NodeCatalogPostInternal


class NodesCatalogsRedactor:
    def __init__(self, log: logging.Logger, redactor: NodesSecretsRedactor):
        self.log = log
        self._redactor = redactor

    def redact(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return data

        catalog = data.get("catalog")
        if not isinstance(catalog, dict):
            return data

        for resources_key in ["resources", "resources_exported"]:
            resources = catalog.get(resources_key)
            if isinstance(resources, list):
                for resource in resources:
                    if not isinstance(resource, dict):
                        continue
                    parameters = resource.get("parameters")
                    if isinstance(parameters, dict):
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
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [
                        ("placement", pymongo.ASCENDING),
                        ("node_id", pymongo.ASCENDING),
                        ("id", pymongo.ASCENDING),
                        ("catalog.catalog_uuid", pymongo.ASCENDING),
                    ],
                    unique=True,
                    name="idx_placement_node_id_catalog_uuid",
                ),
                pymongo.IndexModel(
                    [("catalog.status", pymongo.ASCENDING)], name="idx_catalog_status"
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()
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

        if return_none:
            await self._create_base(payload=data)
            return None
        result = await self._create(fields=fields, payload=data)
        return NodeCatalogGet(**result)

    async def delete_all_from_node(self, node_id: str):
        query = {"node_id": node_id}
        await self._coll.delete_many(filter=query)

    async def drop_created_no_report_ttl(
        self,
        _id: datetime,
        node_id: str,
    ):
        query = {
            "id": _id,
            "node_id": node_id,
        }
        await self._coll.update_one(
            filter=query,
            update={"$unset": {"created_no_report_ttl": ""}},
        )

    async def get(
        self,
        _id: datetime | str,
        node_id: str,
        fields: list,
    ) -> NodeCatalogGet:
        query = {
            "id": _id,
            "node_id": node_id,
        }
        result = await self._get(query=query, fields=fields)
        return NodeCatalogGet(**result)

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
        catalog_status: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> NodeCatalogGetMulti:
        query = {"node_id": node_id}
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
