import asyncio
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
from pyppetdb.model.nodes_groups import NodeGroupGet
from pyppetdb.model.nodes_groups import NodeGroupGetMulti
from pyppetdb.model.nodes_groups import NodeGroupUpdate
from pyppetdb.model.nodes_groups import NodeGroupUpdateInternal
from pyppetdb.model.pdb_facts import PuppetDBFacts


class NodesGroupsCache:
    def __init__(self, log: logging.Logger, coll: AsyncIOMotorCollection):
        self._coll = coll
        self._log = log
        self._cache = {}
        self._initialized = False

    @property
    def cache(self) -> dict["str", NodeGroupGet]:
        return self._cache

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    async def _watch_changes(self):
        try:
            pipeline = [
                {
                    "$project": {
                        "fullDocument.id": 1,
                        "fullDocument.filters": 1,
                        "operationType": 1,
                        "documentKey._id": 1,
                    }
                }
            ]

            async with self.coll.watch(
                full_document="updateLookup",
                pipeline=pipeline,
            ) as change_stream:
                self.log.info("Change stream watcher started for nodes_groups")
                async for change in change_stream:
                    await self._handle_change(change)

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error in nodes_groups change stream: {err}")
        except Exception as err:
            self.log.error(f"Unexpected error in nodes_groups change stream: {err}")

    async def _handle_change(self, change):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]

        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if doc:
                self.cache[doc_id] = NodeGroupGet(**doc)
            else:
                self.log.warning(f"No fullDocument in {operation} change for {doc_id}")

        elif operation == "delete":
            self.cache.pop(doc_id, None)

        else:
            self.log.warning(f"Unhandled operation type: {operation}")

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({}, {"id": 1, "_id": 1, "filters": 1})
            count = 0
            async for doc in cursor:
                doc_id = doc["_id"]
                if doc_id not in self.cache:
                    self.cache[doc_id] = NodeGroupGet(**doc)
                    count += 1

            self.log.info(f"Loaded {count} initial documents into nodes_groups cache")

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error loading initial data: {err}")
            raise

    async def run(self):
        if self._initialized:
            return
        asyncio.create_task(self._watch_changes())
        await self._load_initial_data()
        self._initialized = True
        self.log.info("NodeGroupsCache initialized successfully")


class CrudNodesGroups(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodesGroups, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._cache = NodesGroupsCache(log=log, coll=coll)

    @property
    def cache(self):
        return self._cache

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [
                ("id", pymongo.ASCENDING),
            ],
            unique=True,
        )
        await self.coll.create_index(
            [
                ("nodes", pymongo.ASCENDING),
            ]
        )
        await self.coll.create_index(
            [
                ("teams", pymongo.ASCENDING),
            ]
        )
        await self.cache.run()
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self,
        _id: str,
        payload: NodeGroupUpdateInternal,
        fields: list,
    ) -> NodeGroupGet | None:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return NodeGroupGet(**result)

    async def delete(
        self,
        _id: str,
    ) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def delete_node_from_nodes_groups(self, node_id):
        query = {}
        update = {"$pull": {"nodes": node_id}}
        await self._coll.update_many(
            filter=query,
            update=update,
        )

    async def delete_team_from_nodes_groups(self, team_id):
        query = {}
        update = {"$pull": {"teams": team_id}}
        await self._coll.update_many(
            filter=query,
            update=update,
        )

    @staticmethod
    def compile_filters_from_node_group(node_group: NodeGroupGet | NodeGroupUpdate):
        or_filter = []
        for _filter in node_group.filters:
            and_filter = []
            for _filter_part in _filter.part:
                and_filter.append(
                    {f"facts.{_filter_part.fact}": {"$in": _filter_part.values}}
                )
            or_filter.append({"$and": and_filter})
        return {"$or": or_filter}

    async def reevaluate_node_membership(self, node_id: str, node_facts: PuppetDBFacts):
        _groups = list()
        for group_data in self.cache.cache.values():
            if not group_data.filters:
                continue
            group_matches = False
            for filter_rule in group_data.filters:
                filter_matches = True
                for filter_part in filter_rule.part:
                    if not self._evaluate_filter_part(filter_part, node_facts.values):
                        filter_matches = False
                        break
                if filter_matches:
                    group_matches = True
                    break
            if group_matches:
                _groups.append(group_data.id)
        updates = [
            pymongo.UpdateMany(
                filter={"id": {"$nin": _groups}},
                update={"$pull": {"nodes": node_id}},
            )
        ]
        if _groups:
            updates.append(
                pymongo.UpdateMany(
                    filter={"id": {"$in": _groups}},
                    update={"$addToSet": {"nodes": node_id}},
                )
            )
        await self.coll.bulk_write(updates)
        return _groups

    @staticmethod
    def _evaluate_filter_part(filter_part, node_facts_values):
        try:
            fact_path = filter_part.fact.split(".")
            current_value = node_facts_values
            for key in fact_path:
                if isinstance(current_value, dict) and key in current_value:
                    current_value = current_value[key]
                else:
                    return False
            return current_value in filter_part.values
        except (KeyError, TypeError, AttributeError):
            return False

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> NodeGroupGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return NodeGroupGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        nodes: typing.Optional[str] = None,
        teams: typing.Optional[str] = None,
        teams_list: typing.Optional[list[str]] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> NodeGroupGetMulti:
        query = {}
        self._filter_list(query, "teams", teams_list)
        self._filter_re(query, "id", _id)
        self._filter_re(query, "nodes", nodes)
        self._filter_re(query, "teams", teams)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return NodeGroupGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: NodeGroupUpdateInternal,
        fields: list,
    ) -> NodeGroupGet:
        query = {"id": _id}
        data = payload.model_dump()
        result = await self._update(query=query, fields=fields, payload=data)
        return NodeGroupGet(**result)
