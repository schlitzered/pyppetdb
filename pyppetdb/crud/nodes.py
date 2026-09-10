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
from datetime import timedelta
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
from pyppetdb.model.nodes import NodeGetCatalogResource
from pyppetdb.model.nodes import NodeGetCatalogResources


from pyppetdb.errors import BackendError

from pyppetdb.helpers.placement import calculate_placement


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
                    [
                        ("catalog.resources_exported.type", pymongo.ASCENDING),
                        ("catalog.resources_exported.title", pymongo.ASCENDING),
                    ],
                    name="idx_exported_resources_title",
                ),
                pymongo.IndexModel(
                    [
                        ("catalog.resources_exported.type", pymongo.ASCENDING),
                        ("catalog.resources_exported.tags", pymongo.ASCENDING),
                    ],
                    name="idx_exported_resources_tags",
                ),
                pymongo.IndexModel(
                    [("catalog.resources.type", pymongo.ASCENDING)],
                    name="idx_resources_type",
                ),
                pymongo.IndexModel(
                    [("catalog.resources.title", pymongo.ASCENDING)],
                    name="idx_resources_title",
                ),
                pymongo.IndexModel(
                    [("catalog.resources.tags", pymongo.ASCENDING)],
                    name="idx_resources_tags",
                ),
                pymongo.IndexModel(
                    [("catalog.resources.exported", pymongo.ASCENDING)],
                    name="idx_resources_exported",
                ),
                pymongo.IndexModel(
                    [("catalog.resources.resource", pymongo.ASCENDING)],
                    name="idx_resources_hash",
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
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()
        if self.config.app.main.facts.index:
            for fact in self.config.app.main.facts.index:
                await self._sync_index(
                    pymongo.IndexModel(
                        [
                            (f"facts.{fact}", pymongo.ASCENDING),
                            ("node_groups", pymongo.ASCENDING),
                        ],
                        name=f"idx_fact_{fact}",
                    )
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
        outdated_threshold: Optional[str] = None,
    ) -> NodeGet:
        computed = self._compute_report_status(
            node=NodeGet(**result),
            outdated_threshold=outdated_threshold,
        )
        stripped = self._strip_report_status_sources(result=result, fields=fields)
        node = NodeGet(**stripped)
        node.report_status_computed = computed.report_status_computed
        return node

    @staticmethod
    def _compute_report_status(
        node: NodeGet,
        outdated_threshold: Optional[str] = None,
    ) -> NodeGet:
        if outdated_threshold:
            threshold_dt = datetime.fromisoformat(
                outdated_threshold.replace("Z", "+00:00")
            )
        else:
            threshold_dt = datetime.now() - timedelta(hours=4)

        report = node.report
        if report:
            report_status = report.status
        else:
            report_status = None
        disabled = node.disabled
        change_report = node.change_report

        if (
            disabled is not True
            and change_report is not None
            and change_report < threshold_dt
        ):
            status_computed = "outdated"
        elif report_status is None:
            status_computed = "unreported"
        else:
            status_computed = report_status

        node.report_status_computed = status_computed
        return node

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
            outdated_threshold=outdated_threshold,
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
        query = {}
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_literal(query, "environment", environment)
        project_filter = [
            {"$eq": ["$$resource.type", resource_type]},
        ]
        if resource_title:
            project_filter.append({"$eq": ["$$resource.title", resource_title]})
        if resource_tags:
            for tag in resource_tags:
                project_filter.append(
                    {"$in": [tag, "$$resource.tags"]},
                )
        pipeline = [
            {"$match": query},
            {
                "$project": {
                    "resources_exported": {
                        "$filter": {
                            "input": "$catalog.resources_exported",
                            "as": "resource",
                            "cond": {"$and": project_filter},
                        }
                    }
                }
            },
            {"$unwind": "$resources_exported"},
            {"$group": {"_id": None, "results": {"$push": "$resources_exported"}}},
        ]
        result = list()
        _results = await self.coll.aggregate(pipeline).to_list(length=None)
        for _result in _results:
            for item in _result["results"]:
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

        if outdated_threshold:
            threshold_dt = datetime.fromisoformat(
                outdated_threshold.replace("Z", "+00:00")
            )
        else:
            threshold_dt = datetime.now() - timedelta(hours=4)

        pipeline = [
            {"$match": query},
            {
                "$addFields": {
                    "report_status_computed": {
                        "$cond": {
                            "if": {
                                "$and": [
                                    {"$ne": ["$disabled", True]},
                                    {"$ne": ["$change_report", None]},
                                    {"$lt": ["$change_report", threshold_dt]},
                                ]
                            },
                            "then": "outdated",
                            "else": {
                                "$cond": {
                                    "if": {"$eq": ["$report.status", None]},
                                    "then": "unreported",
                                    "else": "$report.status",
                                }
                            },
                        }
                    }
                }
            },
        ]

        if report_status:
            pipeline.append(
                {"$match": {"report_status_computed": {"$regex": report_status}}}
            )

        meta_counts_pipeline = [
            {"$group": {"_id": "$report_status_computed", "count": {"$sum": 1}}}
        ]

        paginated_pipeline = []
        if sort and sort_order:
            paginated_pipeline.append({"$sort": dict(self._sort(sort, sort_order))})

        if isinstance(page, int) and page and limit:
            paginated_pipeline.append({"$skip": self._pagination_skip(page, limit)})

        if limit:
            paginated_pipeline.append({"$limit": limit})

        proj = self._projection(fields)
        if proj:
            # Ensure we keep report_status_computed if fields are specified
            if isinstance(proj, dict) and not proj.get("report_status_computed"):
                if any(v == 1 for v in proj.values()):
                    proj["report_status_computed"] = 1
            paginated_pipeline.append({"$project": proj})

        pipeline.append(
            {
                "$facet": {
                    "meta_counts": meta_counts_pipeline,
                    "total_results": [{"$count": "count"}],
                    "paginated_results": paginated_pipeline,
                }
            }
        )

        results = await self.coll.aggregate(pipeline).to_list(length=None)

        if not results:
            return NodeGetMulti(
                result=[],
                meta=NodeGetMultiMeta(result_size=0),
            )

        agg_result = results[0]

        statuses = {
            "changed": 0,
            "unchanged": 0,
            "failed": 0,
            "unreported": 0,
            "outdated": 0,
        }
        for status in agg_result.get("meta_counts", []):
            if status["_id"] in statuses:
                statuses[status["_id"]] = status["count"]

        total_count = 0
        if agg_result.get("total_results"):
            total_count = agg_result["total_results"][0]["count"]

        docs = agg_result.get("paginated_results", [])
        formatted_result = self._format_multi(docs, count=total_count)

        formatted_result["meta"]["status_changed"] = statuses["changed"]
        formatted_result["meta"]["status_unchanged"] = statuses["unchanged"]
        formatted_result["meta"]["status_failed"] = statuses["failed"]
        formatted_result["meta"]["status_unreported"] = statuses["unreported"]
        formatted_result["meta"]["status_outdated"] = statuses["outdated"]
        formatted_result["meta"]["page"] = page
        formatted_result["meta"]["limit"] = limit

        return NodeGetMulti(**formatted_result)

    async def get_ingest_state(self, _id: str) -> Optional[dict]:
        pipeline = [
            {"$match": {"id": _id}},
            {"$limit": 1},
            {
                "$project": {
                    "_id": 0,
                    "has_facts": {"$eq": [{"$type": "$facts"}, "object"]},
                    "has_catalog": {"$eq": [{"$type": "$catalog"}, "object"]},
                    "content_hash": "$catalog.content_hash",
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
            "content_hash": rows[0].get("content_hash"),
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

    async def create(
        self,
        _id: str,
        payload: NodePutInternal,
        fields: list,
    ) -> NodeGet:
        data = payload.model_dump()
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
        data = payload.model_dump()

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
