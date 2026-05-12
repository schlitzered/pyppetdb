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
import typing
from typing import List, Optional, Type

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorClientSession
import pymongo
import pymongo.errors
from pydantic import BaseModel

from pyppetdb.config import Config

from pyppetdb.crud.mixins import FilterMixIn
from pyppetdb.crud.mixins import Format
from pyppetdb.crud.mixins import PaginationSkipMixIn
from pyppetdb.crud.mixins import ProjectionMixIn
from pyppetdb.crud.mixins import SortMixIn

from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import BackendError


class Crud:
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
    ):
        self._config = config
        self._log = log

    @property
    def config(self):
        return self._config

    @property
    def log(self):
        return self._log


class CrudMongo(
    Crud, FilterMixIn, Format, PaginationSkipMixIn, ProjectionMixIn, SortMixIn
):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        schema_model: Optional[Type[BaseModel]] = None,
    ):
        super().__init__(config=config, log=log)
        self._resource_type = coll.name
        self._coll = coll
        self._schema_model = schema_model
        self._indices: List[pymongo.IndexModel] = [
            pymongo.IndexModel(
                [("_version", pymongo.ASCENDING)], name="idx_version_common"
            )
        ]

    @property
    def coll(self):
        return self._coll

    @property
    def resource_type(self):
        return self._resource_type

    async def init(self) -> None:
        await self._setup_schema_validation()
        await self._migrate()
        await self._create_index()

    async def _setup_schema_validation(self) -> None:
        if not self._schema_model:
            return

        self.log.info(f"Setting up schema validation for {self.resource_type}")
        try:
            # Get full schema with definitions
            full_schema = self._schema_model.model_json_schema()
            definitions = full_schema.pop("$defs", {})

            # Dereference and convert to MongoDB compatible schema
            mongo_schema_inner = self._convert_to_mongo_schema(
                schema=full_schema, definitions=definitions
            )
            mongo_schema = {"$jsonSchema": mongo_schema_inner}

            # Check if collection exists
            existing_collections = await self.coll.database.list_collection_names()
            if self.resource_type not in existing_collections:
                await self.coll.database.create_collection(
                    self.resource_type, validator=mongo_schema
                )
            else:
                await self.coll.database.command(
                    "collMod", self.resource_type, validator=mongo_schema
                )
        except Exception as e:
            self.log.error(
                f"Failed to setup schema validation for {self.resource_type}: {e}"
            )

    def _convert_to_mongo_schema(self, schema: dict, definitions: dict = None) -> dict:
        if definitions is None:
            definitions = {}

        # Handle references first
        if "$ref" in schema:
            ref_path = schema["$ref"]
            ref_key = ref_path.split("/")[-1]
            if ref_key in definitions:
                # Recursively convert the referenced definition
                return self._convert_to_mongo_schema(
                    schema=definitions[ref_key], definitions=definitions
                )
            return {}

        m_schema = {}

        # Keywords to preserve (and recursively process if needed)
        keywords = {
            "type": None,
            "properties": None,
            "required": None,
            "items": None,
            "anyOf": None,
            "allOf": None,
            "oneOf": None,
            "enum": None,
            "minimum": None,
            "maximum": None,
            "minLength": None,
            "maxLength": None,
            "pattern": None,
            "additionalProperties": None,
        }

        for k, v in schema.items():
            if k not in keywords and k != "format":
                continue

            if k == "format" and v in ("date-time", "date"):
                m_schema["bsonType"] = "date"
                # Remove type/bsonType if they were already set to string
                m_schema.pop("type", None)
                if "bsonType" in m_schema and m_schema["bsonType"] == "string":
                    m_schema["bsonType"] = "date"

            elif k == "type":
                # Map JSON Schema types to BSON types for better compatibility
                # MongoDB $jsonSchema supports both 'type' and 'bsonType'
                # But 'bsonType' is often more predictable for MongoDB
                type_map = {
                    "integer": "int",
                    "number": "double",
                    "string": "string",
                    "boolean": "bool",
                    "object": "object",
                    "array": "array",
                    "null": "null",
                }
                # Only set bsonType if not already set by 'format'
                if "bsonType" not in m_schema or m_schema["bsonType"] != "date":
                    if isinstance(v, str):
                        m_schema["bsonType"] = type_map.get(v, v)
                    elif isinstance(v, list):
                        m_schema["bsonType"] = [type_map.get(t, t) for t in v]

            elif k == "properties":
                m_schema[k] = {
                    pk: self._convert_to_mongo_schema(pv, definitions)
                    for pk, pv in v.items()
                }

            elif k == "items":
                if isinstance(v, dict):
                    m_schema[k] = self._convert_to_mongo_schema(v, definitions)
                else:
                    m_schema[k] = v

            elif k in ("anyOf", "allOf", "oneOf"):
                m_schema[k] = [
                    (
                        self._convert_to_mongo_schema(item, definitions)
                        if isinstance(item, dict)
                        else item
                    )
                    for item in v
                ]

            else:
                m_schema[k] = v

        return m_schema

    async def _create_index(self) -> None:
        if not self._indices:
            return

        self.log.info(f"Syncing indices for {self.resource_type}")
        for index in self._indices:
            await self._sync_index(index)

    async def _sync_index(self, index: pymongo.IndexModel) -> None:
        try:
            await self.coll.create_indexes([index])
        except pymongo.errors.OperationFailure as e:
            if e.code == 85:  # IndexOptionsConflict
                existing_indices = await self.coll.list_indexes().to_list(length=None)

                target_key = index.document.get("key")
                target_name = index.document.get("name")

                for existing in existing_indices:
                    ext_key = existing.get("key")
                    ext_name = existing.get("name")

                    if ext_key == target_key and ext_name != target_name:
                        self.log.info(
                            f"Dropping index {ext_name} because it has same keys as {target_name} but different name"
                        )
                        await self.coll.drop_index(ext_name)
                        await self.coll.create_indexes([index])
                        return

                    if ext_name == target_name and ext_key != target_key:
                        self.log.info(f"Dropping index {ext_name} because keys changed")
                        await self.coll.drop_index(ext_name)
                        await self.coll.create_indexes([index])
                        return
                raise
            else:
                raise
        except Exception as e:
            self.log.error(f"Failed to sync index for {self.resource_type}: {e}")

    async def _migrate(self) -> None:
        self.log.info(f"Checking for migrations for {self.resource_type}")
        # Add future migrations to this list
        migrations = [
            self.migrate_1,
        ]
        for migration in migrations:
            await self._run_migration_transactional(migration)

    async def _run_migration_transactional(self, migration_func: typing.Callable):
        try:
            # Try to use a session for transactions (requires Replica Set)
            async with await self.coll.database.client.start_session() as session:
                try:
                    async with session.start_transaction():
                        await migration_func(session=session)
                except pymongo.errors.OperationFailure as e:
                    # If transactions are not supported (e.g. standalone Mongo)
                    if e.code == 20:  # IllegalOperation
                        self.log.debug(
                            f"Transactions not supported for {self.resource_type}, running without"
                        )
                        await migration_func()
                    else:
                        raise
        except (pymongo.errors.OperationFailure, pymongo.errors.ConfigurationError):
            # Fallback if sessions are not supported at all
            await migration_func()

    async def migrate_1(
        self, session: Optional[AsyncIOMotorClientSession] = None
    ) -> None:
        # Migration 1: Set _version to 1 for all objects that have a _version field.
        query = {"_version": {"$exists": True, "$lt": 1}}

        count = await self.coll.count_documents(query, session=session)
        if count == 0:
            return

        self.log.info(
            f"Migrating {count} {self.resource_type} objects to version 1 in chunks"
        )

        modified_total = 0
        while True:
            # Find a batch of documents to update
            cursor = self.coll.find(query, session=session).limit(1000)
            batch = await cursor.to_list(length=1000)
            if not batch:
                break

            ids = [doc["_id"] for doc in batch]
            res = await self.coll.update_many(
                {"_id": {"$in": ids}}, {"$set": {"_version": 1}}, session=session
            )
            modified_total += res.modified_count

        if modified_total > 0:
            self.log.info(
                f"Migrated {modified_total} {self.resource_type} objects to version 1"
            )

    async def _create_ttl_index(
        self, field: str, ttl_seconds: int, index_name: str
    ) -> None:
        if ttl_seconds is None:
            return

        indexes = await self.coll.list_indexes().to_list(length=None)
        existing_index = None
        for index in indexes:
            # Check by name OR by key (to find autogenerated names like field_1)
            key_spec = index.get("key", {})
            if index.get("name") == index_name or key_spec == {field: 1}:
                existing_index = index
                break

        if existing_index:
            current_ttl = existing_index.get("expireAfterSeconds")
            current_name = existing_index.get("name")
            key_spec = existing_index.get("key", {})
            current_field = next(iter(key_spec.keys()), None)

            # Check if both field and TTL match
            if (
                current_field == field
                and current_ttl == ttl_seconds
                and current_name == index_name
            ):
                self.log.debug(
                    f"TTL index {index_name} already exists with correct field '{field}' and TTL ({ttl_seconds}s)"
                )
                return
            else:
                self.log.info(
                    f"Dropping index {current_name} (current field: '{current_field}', current TTL: {current_ttl}s) to recreate as {index_name} with TTL {ttl_seconds}s"
                )
                await self.coll.drop_index(current_name)

        self.log.info(
            f"Creating TTL index {index_name} on field '{field}' with TTL {ttl_seconds}s"
        )
        await self.coll.create_index(
            [(field, pymongo.ASCENDING)],
            expireAfterSeconds=ttl_seconds,
            name=index_name,
        )

    async def _create(
        self,
        payload: dict,
        fields: list = None,
        return_none: bool = False,
    ) -> dict | None:
        if "_version" not in payload:
            payload["_version"] = 1
        try:
            _id = await self._coll.insert_one(payload)
            if return_none:
                return None
            return await self._get_by_obj_id(_id=_id.inserted_id, fields=fields)
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateResource
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

    async def _delete(self, query: dict) -> dict:
        try:
            result = await self._coll.delete_one(filter=query)
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()
        if result.deleted_count == 0:
            raise ResourceNotFound
        return {}

    async def _delete_many(self, query: dict) -> dict:
        try:
            await self._coll.delete_many(filter=query)
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()
        return {}

    async def _get(self, query: dict, fields: list) -> dict:
        try:
            result = await self._coll.find_one(
                filter=query, projection=self._projection(fields)
            )
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError
        if result is None:
            if "node_groups" in query:
                query.pop("node_groups")
            raise ResourceNotFound(
                details=f"Resource {self.resource_type} {query} not found"
            )
        return self._format(result)

    async def _get_by_obj_id(self, _id, fields: list) -> dict:
        query = {"_id": _id}
        return await self._get(query=query, fields=fields)

    async def _resource_exists(self, query: dict) -> ObjectId:
        result = await self._get(query=query, fields=["id"])
        return result["id"]

    async def _search(
        self,
        query: dict,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[str] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> dict:
        try:
            count = await self._coll.count_documents(
                filter=query,
            )
            cursor = self._coll.find(filter=query, projection=self._projection(fields))
            if sort and sort_order:
                cursor.sort(self._sort(sort=sort, sort_order=sort_order))
            if isinstance(page, int) and page and limit:
                cursor.skip(self._pagination_skip(page, limit))
            return self._format_multi(
                list(await cursor.to_list(limit)),
                count=count,
            )
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError

    async def _update(
        self, query: dict, payload: dict, fields: list, upsert=False
    ) -> dict:
        update = {"$set": {}}
        for k, v in payload.items():
            if v is None:
                continue
            update["$set"][k] = v
        try:
            result = await self._coll.find_one_and_update(
                filter=query,
                update=update,
                projection=self._projection(fields=fields),
                return_document=pymongo.ReturnDocument.AFTER,
                upsert=upsert,
            )
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateResource
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError
        if result is None:
            raise ResourceNotFound
        return self._format(result)
