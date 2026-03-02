from datetime import datetime, timedelta
import logging
import random
import typing

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import filter_complex_search
from pyppetdb.model.nodes_catalog_cache import NodeCatalogCacheGet
from pyppetdb.model.nodes_catalog_cache import NodeCatalogCachePutInternal
from pyppetdb.errors import ResourceNotFound


class CrudNodesCatalogCache(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudNodesCatalogCache, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index([("placement", pymongo.ASCENDING)])

        await self.coll.create_index(
            [("ttl", pymongo.ASCENDING)],
            expireAfterSeconds=0,
            name="ttl_catalog_cache",
        )
        self.log.info(f"creating {self.resource_type} indices, done")

    async def get(
        self,
        node_id: str,
        fields: list,
    ) -> NodeCatalogCacheGet:
        query = {"id": node_id}
        try:
            result = await self._get(query=query, fields=fields)
            result["cached"] = True
            return NodeCatalogCacheGet(**result)
        except ResourceNotFound:
            # Return a response indicating no cache exists
            return NodeCatalogCacheGet(id=node_id, cached=False)

    async def get_catalog(
        self,
        node_id: str,
    ) -> typing.Any | None:
        query = {"id": node_id}
        try:
            result = await self._coll.find_one(filter=query, projection={"catalog": 1})
            if result:
                return result.get("catalog")
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
        return None

    async def upsert(
        self,
        node_id: str,
        facts: typing.Dict[str, str],
        catalog: typing.Any,
    ) -> None:
        ttl_seconds = self.config.app.puppet.catalogCacheTTL
        random_factor = random.uniform(0.75, 1.25)
        ttl = datetime.utcnow() + timedelta(seconds=int(ttl_seconds * random_factor))

        payload = NodeCatalogCachePutInternal(
            id=node_id,
            facts=facts,
            catalog=catalog,
            placement=self.config.mongodb.placement,
            ttl=ttl,
        )

        query = {"id": node_id}
        data = payload.model_dump()

        await self.coll.update_one(
            filter=query,
            update={"$set": data},
            upsert=True,
        )

    async def delete(
        self,
        node_id: str,
    ) -> DataDelete:
        query = {"id": node_id}
        await self._delete(query=query)
        return DataDelete()

    async def delete_many_by_filter(
        self,
        environment: typing.Optional[str] = None,
        fact: typing.Optional[filter_complex_search] = None,
    ) -> int:
        query = {}
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_literal(query, "environment", environment)

        result = await self.coll.delete_many(filter=query)
        return result.deleted_count
