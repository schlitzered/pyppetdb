import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

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
    ):
        super().__init__(config=config, log=log)
        self._resource_type = coll.name
        self._coll = coll

    @property
    def coll(self):
        return self._coll

    @property
    def resource_type(self):
        return self._resource_type

    async def index_create(self) -> None:
        raise NotImplementedError

    async def _create_ttl_index(
        self, field: str, ttl_seconds: int, index_name: str
    ) -> None:
        if ttl_seconds is None:
            return

        indexes = await self.coll.list_indexes().to_list(length=None)
        existing_index = None
        for index in indexes:
            if index.get("name") == index_name:
                existing_index = index
                break

        if existing_index:
            current_ttl = existing_index.get("expireAfterSeconds")
            # Extract the current indexed field from the key specification
            current_field = None
            key_spec = existing_index.get("key", {})
            if key_spec:
                current_field = next(iter(key_spec.keys()), None)

            # Check if both field and TTL match
            if current_field == field and current_ttl == ttl_seconds:
                self.log.debug(
                    f"TTL index {index_name} already exists with correct field '{field}' and TTL ({ttl_seconds}s)"
                )
                return
            else:
                self.log.info(
                    f"Dropping TTL index {index_name} (current field: '{current_field}', new field: '{field}', current TTL: {current_ttl}s, new TTL: {ttl_seconds}s)"
                )
                await self.coll.drop_index(index_name)

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
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError
        if result is None:
            raise ResourceNotFound
        return self._format(result)
