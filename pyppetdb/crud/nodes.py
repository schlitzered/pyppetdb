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
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Optional

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.nodes import NodeGet
from pyppetdb.model.nodes import NodeGetMulti
from pyppetdb.model.nodes import NodeGetMultiMeta
from pyppetdb.model.nodes import NodePutInternal
from pyppetdb.model.nodes import NodeDistinctFactValue
from pyppetdb.model.nodes import NodeGetDistinctFactValues
from pyppetdb.model.nodes import NodeGetDistinctFactNames
from pyppetdb.model.nodes import NodeGetCatalogResource
from pyppetdb.model.nodes import NodeGetCatalogResources


from pyppetdb.errors import BackendError
from pyppetdb.errors import QueryParamValidationError

from pyppetdb.helpers.placement import calculate_placement
from pyppetdb.helpers.puppetdb import FACT_PATHS_FIELD
from pyppetdb.helpers.puppetdb import build_fact_paths
from pyppetdb.helpers.puppetdb import build_facts_index
from pyppetdb.helpers.puppetdb import decode_fact_path
from pyppetdb.helpers.puppetdb import dotted_fact_name


REPORT_STATUSES = ("changed", "unchanged", "failed", "unreported", "outdated")
OUTDATED_AFTER = timedelta(hours=4)


class CrudNodes(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodes, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING)], unique=True, name="idx_id"
                ),
                pymongo.IndexModel(
                    [("disabled", pymongo.ASCENDING)], name="idx_disabled"
                ),
                pymongo.IndexModel(
                    [("disabled", pymongo.ASCENDING), ("report.status", pymongo.ASCENDING)],
                    name="idx_disabled_report_status",
                ),
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING), ("disabled", pymongo.ASCENDING)],
                    name="idx_package_inventory",
                    partialFilterExpression={"package_inventory": {"$type": "array"}},
                ),
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING), ("disabled", pymongo.ASCENDING)],
                    name="idx_catalog_inputs",
                    partialFilterExpression={"catalog_inputs": {"$type": "object"}},
                ),
                pymongo.IndexModel(
                    [("node_groups", pymongo.ASCENDING)], name="idx_node_groups"
                ),
                pymongo.IndexModel(
                    [("change_catalog", pymongo.ASCENDING)], name="idx_change_catalog"
                ),
                pymongo.IndexModel(
                    [("change_facts", pymongo.ASCENDING)], name="idx_change_facts"
                ),
                pymongo.IndexModel(
                    [("change_last", pymongo.ASCENDING)], name="idx_change_last"
                ),
                pymongo.IndexModel(
                    [("change_report", pymongo.ASCENDING)], name="idx_change_report"
                ),
                pymongo.IndexModel(
                    [("report.status", pymongo.ASCENDING)], name="idx_report_status"
                ),
                pymongo.IndexModel(
                    [("remote_agent.connected", pymongo.ASCENDING)],
                    name="idx_remote_agent_connected",
                ),
                pymongo.IndexModel(
                    [("producer", pymongo.ASCENDING)], name="idx_producer"
                ),
                pymongo.IndexModel(
                    [("report.end_time", pymongo.DESCENDING)],
                    name="idx_report_end_time",
                ),
                pymongo.IndexModel(
                    [("environment", pymongo.ASCENDING)], name="idx_environment"
                ),
                pymongo.IndexModel(
                    [("report.hash", pymongo.ASCENDING)], name="idx_report_hash"
                ),
                pymongo.IndexModel(
                    [
                        ("facts_index.p", pymongo.ASCENDING),
                        ("facts_index.v", pymongo.ASCENDING),
                    ],
                    name="idx_facts_index",
                ),
                pymongo.IndexModel(
                    [(FACT_PATHS_FIELD, pymongo.ASCENDING)],
                    name="idx_fact_paths",
                ),
            ]
        )

    async def delete(
        self,
        _id: str,
    ) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def delete_node_group_from_all(self, node_group_id: str):
        await self.coll.update_many(
            filter={"node_groups": node_group_id},
            update={
                "$pull": {"node_groups": node_group_id},
            },
        )

    _report_status_source_fields = ("report.status", "disabled", "change_report")

    @staticmethod
    def _fields_with_report_status_sources(fields: Optional[list]) -> Optional[list]:
        if not fields:
            return fields
        extended = list(fields)
        for source in CrudNodes._report_status_source_fields:
            parent = source.split(".", 1)[0]
            if source not in extended and parent not in extended:
                extended.append(source)
        return extended

    @staticmethod
    def _strip_report_status_sources(result: dict, fields: Optional[list]) -> dict:
        if not fields:
            return result
        requested = set(fields)
        if "disabled" not in requested:
            result.pop("disabled", None)
        if "change_report" not in requested:
            result.pop("change_report", None)
        if "report" not in requested:
            if not any(field.startswith("report.") for field in requested):
                result.pop("report", None)
            elif "report.status" not in requested and isinstance(
                result.get("report"), dict
            ):
                result["report"].pop("status", None)
        return result

    def _build_node_response(
        self,
        result: dict,
        fields: Optional[list],
        threshold: Optional[datetime] = None,
    ) -> NodeGet:
        computed = self._compute_report_status(
            node=result,
            threshold=threshold or self._outdated_threshold(None),
        )
        stripped = self._strip_report_status_sources(result=result, fields=fields)
        node = NodeGet(**stripped)
        node.report_status_computed = computed
        return node

    @staticmethod
    def _outdated_threshold(outdated_threshold: Optional[str]) -> datetime:
        if not outdated_threshold:
            return datetime.now(timezone.utc).replace(tzinfo=None) - OUTDATED_AFTER
        threshold = datetime.fromisoformat(outdated_threshold.replace("Z", "+00:00"))
        if threshold.tzinfo:
            threshold = threshold.astimezone(timezone.utc).replace(tzinfo=None)
        return threshold

    @staticmethod
    def _compute_report_status(node: dict, threshold: datetime) -> str:
        report = node.get("report")
        report_status = report.get("status") if isinstance(report, dict) else None
        change_report = node.get("change_report")
        if (
            node.get("disabled") is not True
            and isinstance(change_report, datetime)
            and change_report < threshold
        ):
            return "outdated"
        if report_status is None:
            return "unreported"
        return report_status

    @staticmethod
    def _outdated_query(threshold: datetime) -> dict:
        return {"disabled": {"$ne": True}, "change_report": {"$lt": threshold}}

    @classmethod
    def _report_status_query(cls, report_status: str, threshold: datetime) -> dict:
        try:
            pattern = re.compile(report_status)
        except re.error as err:
            raise QueryParamValidationError(msg=f"invalid report_status regex: {err}")
        not_outdated = {
            "$or": [
                {"disabled": True},
                {"change_report": {"$not": {"$lt": threshold}}},
            ]
        }
        branches = [{"$and": [not_outdated, {"report.status": {"$regex": report_status}}]}]
        if pattern.search("unreported"):
            branches.append({"$and": [not_outdated, {"report.status": None}]})
        if pattern.search("outdated"):
            branches.append(cls._outdated_query(threshold))
        return {"$or": branches}

    async def _report_status_counts(
        self, query: dict, threshold: datetime
    ) -> tuple[dict, int]:
        outdated = {
            "$and": [
                {"$ne": ["$disabled", True]},
                {"$eq": [{"$type": "$change_report"}, "date"]},
                {"$lt": ["$change_report", threshold]},
            ]
        }
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": {"outdated": outdated, "status": "$report.status"},
                    "count": {"$sum": 1},
                }
            },
        ]
        counts = dict.fromkeys(REPORT_STATUSES, 0)
        total = 0
        for row in await self.coll.aggregate(pipeline).to_list(length=None):
            total += row["count"]
            if row["_id"]["outdated"]:
                status = "outdated"
            else:
                status = row["_id"].get("status") or "unreported"
            if status in counts:
                counts[status] += row["count"]
        return counts, total

    async def get(
        self,
        _id: str,
        fields: list,
        user_node_groups: Optional[list[str]] = None,
        outdated_threshold: Optional[str] = None,
    ) -> NodeGet:
        query = {"id": _id}
        self._filter_list(query, "node_groups", user_node_groups)
        result = await self._get(
            query=query,
            fields=self._fields_with_report_status_sources(fields),
        )
        return self._build_node_response(
            result=result,
            fields=fields,
            threshold=self._outdated_threshold(outdated_threshold),
        )

    async def resource_exists(
        self,
        _id: str,
        user_node_groups: Optional[list[str]] = None,
    ) -> ObjectId:
        query = {"id": _id}
        self._filter_list(query, "node_groups", user_node_groups)
        return await self._resource_exists(query=query)

    async def exported_resources(
        self,
        resource_type: str,
        user_node_groups: Optional[list[str]] = None,
        resource_title: Optional[str] = None,
        resource_tags: Optional[list[str]] = None,
        disabled: Optional[bool] = None,
        fact: Optional[set[str]] = None,
        environment: Optional[str] = None,
    ) -> NodeGetCatalogResources:
        node_query = {}
        self._filter_list(node_query, "node_groups", user_node_groups)
        self._filter_complex_search(
            node_query, base_attribute="facts", complex_search=fact
        )

        resource_query = {"exported": True, "type": resource_type}
        self._filter_boolean(resource_query, "disabled", disabled)
        self._filter_literal(resource_query, "environment", environment)
        if resource_title:
            resource_query["title"] = resource_title
        if resource_tags:
            resource_query["tags"] = {"$all": resource_tags}

        if node_query:
            node_ids = await self._coll.distinct("id", filter=node_query)
            resource_query["node_id"] = {"$in": node_ids}

        resources_coll = self.coll.database["nodes_resources"]
        cursor = resources_coll.find(
            filter=resource_query,
            projection={
                "_id": 0,
                "resource": 1,
                "type": 1,
                "title": 1,
                "exported": 1,
                "tags": 1,
                "file": 1,
                "line": 1,
                "parameters": 1,
            },
        )
        result = list()
        async for item in cursor:
            result.append(NodeGetCatalogResource(**item))
        return NodeGetCatalogResources(
            **{"result": result, "meta": {"result_size": len(result)}}
        )

    async def distinct_fact_values(
        self,
        user_node_groups: Optional[list[str]] = None,
        fact_id: Optional[str] = None,
        disabled: Optional[bool] = None,
        fact: Optional[set] = None,
        environment: Optional[str] = None,
        report_status: Optional[str] = None,
    ) -> NodeGetDistinctFactValues:
        if not fact_id or fact_id.endswith("."):
            return NodeGetDistinctFactValues(
                **{"result": [], "meta": {"result_size": 0}}
            )

        query = {
            f"facts.{fact_id}": {
                "$type": [
                    "string",
                    "number",
                    "bool",
                    "date",
                ]
            }
        }
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_literal(query, "environment", environment)
        self._filter_literal(query, "report.status", report_status)

        pipeline = [
            {"$match": query},
            {"$group": {"_id": f"$facts.{fact_id}", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},  # Optional: sort by descending order of frequency
        ]
        result = list()
        for item in await self.coll.aggregate(pipeline).to_list(length=None):
            result.append(NodeDistinctFactValue(value=item["_id"], count=item["count"]))
        return NodeGetDistinctFactValues(
            **{"result": result, "meta": {"result_size": len(result)}}
        )

    async def distinct_fact_names(
        self,
        user_node_groups: Optional[list[str]] = None,
        disabled: Optional[bool] = None,
        fact: Optional[set] = None,
        environment: Optional[str] = None,
        report_status: Optional[str] = None,
    ) -> NodeGetDistinctFactNames:
        query = {}
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_literal(query, "environment", environment)
        self._filter_literal(query, "report.status", report_status)

        entries = await self._distinct_fact_paths(query)
        names = set()
        for entry in entries:
            if isinstance(entry, str):
                names.add(dotted_fact_name(decode_fact_path(entry)[0]))
        result = sorted(names)
        return NodeGetDistinctFactNames(
            **{"result": result, "meta": {"result_size": len(result)}}
        )

    async def _distinct_fact_paths(self, query: dict) -> list:
        try:
            if not query:
                return await self.coll.distinct(FACT_PATHS_FIELD)
            pipeline = [
                {"$match": query},
                {"$group": {"_id": f"${FACT_PATHS_FIELD}"}},
                {"$unwind": "$_id"},
                {"$group": {"_id": "$_id"}},
            ]
            return [
                item["_id"]
                for item in await self.coll.aggregate(pipeline).to_list(length=None)
            ]
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

    async def count(
        self,
        user_node_groups: Optional[list[str]] = None,
        disabled: Optional[bool] = None,
        environment: Optional[str] = None,
        fact: Optional[set[str]] = None,
        report_status: Optional[str] = None,
        remote_agent_connected: Optional[bool] = None,
        remote_agent_via: Optional[str] = None,
        query: Optional[dict] = None,
    ) -> int:
        if not query:
            query = {}
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_re(query, "environment", environment)
        self._filter_re(query, "report.status", report_status)
        self._filter_boolean(query, "remote_agent.connected", remote_agent_connected)
        self._filter_re(query, "remote_agent.via", remote_agent_via)
        return await self.coll.count_documents(query)

    async def ids(self, query: dict) -> list[str]:
        try:
            docs = await self.coll.find(
                query, projection={"_id": 0, "id": 1}
            ).to_list(length=None)
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()
        return [doc["id"] for doc in docs]

    async def search(
        self,
        _id: Optional[str] = None,
        user_node_groups: Optional[list[str]] = None,
        disabled: Optional[bool] = None,
        environment: Optional[str] = None,
        fact: Optional[set[str]] = None,
        report_status: Optional[str] = None,
        outdated_threshold: Optional[str] = None,
        remote_agent_connected: Optional[bool] = None,
        remote_agent_via: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        query: Optional[dict] = None,
    ) -> NodeGetMulti:
        if not query:
            query = {}
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_re(query, "environment", environment)
        self._filter_re(query, "id", _id)
        self._filter_boolean(query, "remote_agent.connected", remote_agent_connected)
        self._filter_re(query, "remote_agent.via", remote_agent_via)

        threshold = self._outdated_threshold(outdated_threshold)
        if report_status:
            status_query = self._report_status_query(report_status, threshold)
            query = {"$and": [query, status_query]} if query else status_query

        counts = {}

        async def count(match: dict) -> int:
            status_counts, total = await self._report_status_counts(match, threshold)
            counts.update(status_counts)
            return total

        result = await self._search(
            query=query,
            fields=self._fields_with_report_status_sources(fields),
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
            count=count,
        )
        nodes = [
            self._build_node_response(item, fields, threshold)
            for item in result["result"]
        ]
        if not limit:
            counts = dict.fromkeys(REPORT_STATUSES, 0)
            for node in nodes:
                if node.report_status_computed in counts:
                    counts[node.report_status_computed] += 1
        return NodeGetMulti(
            result=nodes,
            meta=NodeGetMultiMeta(
                result_size=result["meta"]["result_size"],
                **{f"status_{status}": counts[status] for status in REPORT_STATUSES},
            ),
        )

    async def get_ingest_state(self, _id: str) -> Optional[dict]:
        pipeline = [
            {"$match": {"id": _id}},
            {"$limit": 1},
            {
                "$project": {
                    "_id": 0,
                    "has_facts": {"$eq": [{"$type": "$facts"}, "object"]},
                    "has_catalog": {"$eq": [{"$type": "$catalog"}, "object"]},
                    "catalog_uuid": "$catalog.catalog_uuid",
                    "content_hash": "$catalog.content_hash",
                    "disabled": {"$ifNull": ["$disabled", False]},
                    "environment": "$environment",
                    "placement": "$placement",
                }
            },
        ]
        try:
            rows = await self._coll.aggregate(pipeline).to_list(length=1)
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()
        if not rows:
            return None
        return {
            "has_facts": rows[0]["has_facts"],
            "has_catalog": rows[0]["has_catalog"],
            "catalog_uuid": rows[0].get("catalog_uuid"),
            "content_hash": rows[0].get("content_hash"),
            "disabled": bool(rows[0].get("disabled")),
            "environment": rows[0].get("environment"),
            "placement": rows[0].get("placement"),
        }

    async def update_catalog_metadata(self, _id: str, metadata: dict) -> None:
        if not metadata:
            return
        update = {f"catalog.{key}": value for key, value in metadata.items()}
        try:
            await self._coll.update_one(
                filter={"id": _id},
                update={"$set": update},
            )
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

    async def get_placement(self, _id: str) -> dict[str, str]:
        if not self.config.mongodb.placementFacts:
            return {}

        projection = {f"facts.{fact}": 1 for fact in self.config.mongodb.placementFacts}
        try:
            node = await self._coll.find_one({"id": _id}, projection=projection)
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

        facts = node.get("facts", {}) if node else {}
        return calculate_placement(self.config, facts)

    def _with_facts_index(self, data: dict) -> dict:
        facts = data.get("facts")
        if not isinstance(facts, dict):
            return data
        settings = self.config.app.main.facts
        data["facts_index"] = build_facts_index(
            facts,
            max_value_len=settings.indexMaxValueLen,
            depth=settings.indexDepth,
            deny=settings.indexDeny,
        )
        data[FACT_PATHS_FIELD] = build_fact_paths(facts)
        return data

    async def create(
        self,
        _id: str,
        payload: NodePutInternal,
        fields: list,
    ) -> NodeGet:
        data = self._with_facts_index(payload.model_dump())
        data["id"] = _id

        result = await self._create(
            payload=data,
            fields=self._fields_with_report_status_sources(fields),
        )
        return self._build_node_response(result=result, fields=fields)

    async def update(
        self,
        _id: str,
        payload: NodePutInternal,
        fields: list,
        upsert: bool = False,
        return_none: bool = False,
    ) -> NodeGet | None:
        query = {"id": _id}
        data = self._with_facts_index(payload.model_dump())

        result = await self._update(
            query=query,
            fields=self._fields_with_report_status_sources(fields),
            payload=data,
            upsert=upsert,
        )
        if return_none:
            return None
        return self._build_node_response(result=result, fields=fields)

    async def update_remote_agent_status(
        self,
        node_id: str,
        connected: bool,
        via: Optional[str] = None,
    ):
        update_data = {
            "remote_agent.connected": connected,
            "remote_agent.via": via,
        }
        await self.coll.update_one(
            filter={"id": node_id},
            update={"$set": update_data},
        )

    async def update_remote_agent_current_job_id(
        self,
        node_id: str,
        current_job_id: list[str],
    ):
        update_data = {
            "remote_agent.current_job_id": current_job_id,
        }
        await self.coll.update_one(
            filter={"id": node_id},
            update={"$set": update_data},
        )

    async def cleanup_remote_agents(self, via: str):
        self.log.info(f"Cleaning up remote agents for instance '{via}'")
        await self.coll.update_many(
            filter={"remote_agent.via": via},
            update={
                "$set": {
                    "remote_agent.connected": False,
                    "remote_agent.via": None,
                }
            },
        )

    async def update_nodegroup(
        self,
        node_group_id: str,
        nodes: list[str],
    ):
        await self.coll.update_many(
            filter={"id": {"$nin": nodes}, "node_groups": node_group_id},
            update={
                "$pull": {"node_groups": node_group_id},
            },
        )
        if nodes:
            await self.coll.update_many(
                filter={
                    "id": {"$in": nodes},
                    "node_groups": {"$ne": node_group_id},
                },
                update={
                    "$addToSet": {"node_groups": node_group_id},
                },
            )
