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
from pyppetdb.model.common import filter_complex_search
from pyppetdb.model.nodes import NodeGet
from pyppetdb.model.nodes import NodeGetMulti
from pyppetdb.model.nodes import NodePutInternal
from pyppetdb.model.nodes import NodeDistinctFactValue
from pyppetdb.model.nodes import NodeGetDistinctFactValues
from pyppetdb.model.nodes import NodeGetCatalogResource
from pyppetdb.model.nodes import NodeGetCatalogResources


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

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("disabled", pymongo.ASCENDING)])
        await self.coll.create_index(
            [
                ("node_groups", pymongo.ASCENDING),
            ]
        )
        await self.coll.create_index([("change_catalog", pymongo.ASCENDING)])
        await self.coll.create_index([("change_facts", pymongo.ASCENDING)])
        await self.coll.create_index([("change_last", pymongo.ASCENDING)])
        await self.coll.create_index([("change_report", pymongo.ASCENDING)])
        await self.coll.create_index([("report.status", pymongo.ASCENDING)])
        for fact in self.config.app.main.facts.index:
            await self.coll.create_index(
                [
                    (f"facts.{fact}", pymongo.ASCENDING),
                    ("node_groups", pymongo.ASCENDING),
                ]
            )
        await self.coll.create_index(
            [
                ("catalog.resources_exported.type", pymongo.ASCENDING),
                ("catalog.resources_exported.title", pymongo.ASCENDING),
            ]
        )
        await self.coll.create_index(
            [
                ("catalog.resources_exported.type", pymongo.ASCENDING),
                ("catalog.resources_exported.tags", pymongo.ASCENDING),
            ]
        )
        self.log.info(f"creating {self.resource_type} indices, done")

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

    async def get(
        self,
        _id: str,
        fields: list,
        user_node_groups: typing.Optional[list[str]] = None,
    ) -> NodeGet:
        query = {"id": _id}
        self._filter_list(query, "node_groups", user_node_groups)
        result = await self._get(query=query, fields=fields)
        return NodeGet(**result)

    async def resource_exists(
        self,
        _id: str,
        user_node_groups: typing.Optional[list[str]] = None,
    ) -> ObjectId:
        query = {"id": _id}
        self._filter_list(query, "node_groups", user_node_groups)
        return await self._resource_exists(query=query)

    async def exported_resources(
        self,
        resource_type: str,
        user_node_groups: typing.Optional[list[str]] = None,
        resource_title: typing.Optional[str] = None,
        resource_tags: typing.Optional[list[str]] = None,
        disabled: typing.Optional[bool] = None,
        fact: typing.Optional[filter_complex_search] = None,
        environment: typing.Optional[str] = None,
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
        user_node_groups: typing.Optional[list[str]] = None,
        fact_id: typing.Optional[str] = None,
        disabled: typing.Optional[bool] = None,
        fact: typing.Optional[filter_complex_search] = None,
        environment: typing.Optional[str] = None,
        report_status: typing.Optional[str] = None,
    ) -> NodeGetDistinctFactValues:
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

    async def search(
        self,
        _id: typing.Optional[str] = None,
        user_node_groups: typing.Optional[list[str]] = None,
        disabled: typing.Optional[bool] = None,
        environment: typing.Optional[str] = None,
        fact: typing.Optional[filter_complex_search] = None,
        report_status: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
        query: typing.Optional[dict] = None,
    ) -> NodeGetMulti:
        if not query:
            query = {}
        self._filter_list(query, "node_groups", user_node_groups)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_boolean(query, "disabled", disabled)
        self._filter_re(query, "environment", environment)
        self._filter_re(query, "id", _id)
        self._filter_re(query, "report.status", report_status)
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": {
                        "$cond": {
                            "if": {"$eq": ["$report.status", None]},
                            "then": "unreported",
                            "else": "$report.status",
                        }
                    },
                    "count": {"$sum": 1},
                }
            },
        ]
        statuses = {
            "changed": 0,
            "unchanged": 0,
            "failed": 0,
            None: 0,
        }
        for status in await self.coll.aggregate(pipeline).to_list(length=None):
            statuses[status["_id"]] = status["count"]
        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        result["meta"]["status_changed"] = statuses["changed"]
        result["meta"]["status_unchanged"] = statuses["unchanged"]
        result["meta"]["status_failed"] = statuses["failed"]
        result["meta"]["status_unreported"] = statuses[None]
        return NodeGetMulti(**result)

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
            query=query, fields=fields, payload=data, upsert=upsert
        )
        if return_none:
            return None
        return NodeGet(**result)

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
