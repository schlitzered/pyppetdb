import base64
from datetime import datetime, timedelta, UTC
import hashlib
import json
import logging
import random
import typing
import zlib

from cryptography.fernet import Fernet
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


class NodesDataProtector:
    def __init__(self, app_secret_key: str, log: logging.Logger):
        self.log = log
        self._fernet = self._derive_fernet(app_secret_key)

    @staticmethod
    def _derive_fernet(key: str) -> Fernet:
        digest = hashlib.sha256(key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypt_string(self, cleartext: str) -> str:
        return self._fernet.encrypt(cleartext.encode()).decode()

    def decrypt_string(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    def encrypt_obj(self, data: typing.Any) -> bytes:
        serialized = json.dumps(data, separators=(",", ":")).encode()
        compressed = zlib.compress(serialized)
        return self._fernet.encrypt(compressed)

    def decrypt_obj(self, encrypted_data: bytes) -> typing.Any:
        try:
            decrypted = self._fernet.decrypt(encrypted_data)
            decompressed = zlib.decompress(decrypted)
            return json.loads(decompressed.decode())
        except Exception as e:
            self.log.error(f"Failed to decrypt/decompress data: {e}")
            raise


class CrudNodesCatalogCache(CrudMongo):
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        super(CrudNodesCatalogCache, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._protector = protector

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
            return NodeCatalogCacheGet(id=node_id, cached=False)

    async def get_catalog(
        self,
        node_id: str,
    ) -> typing.Any | None:
        query = {"id": node_id}
        try:
            result = await self._coll.find_one(filter=query, projection={"catalog": 1})
            if result and result.get("catalog"):
                return self._protector.decrypt_obj(result.get("catalog"))
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
        except Exception as err:
            self.log.error(f"failed to decrypt catalog for {node_id}: {err}")
        return None

    async def upsert(
        self,
        node_id: str,
        facts: typing.Dict[str, str],
        catalog: typing.Any,
    ) -> None:
        ttl_seconds = self.config.app.puppet.catalogCacheTTL
        random_factor = random.uniform(0.75, 1.25)
        ttl = datetime.now(UTC) + timedelta(seconds=int(ttl_seconds * random_factor))

        encrypted_catalog = self._protector.encrypt_obj(catalog)

        payload = NodeCatalogCachePutInternal(
            id=node_id,
            facts=facts,
            catalog=encrypted_catalog,
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

    async def get_cached_node_ids(
        self,
        node_ids: typing.List[str],
    ) -> typing.Set[str]:
        if not node_ids:
            return set()

        query = {"id": {"$in": node_ids}}
        cursor = self.coll.find(filter=query, projection={"id": 1})
        cached_ids = set()
        async for doc in cursor:
            cached_ids.add(doc["id"])
        return cached_ids

    async def delete_many_by_filter(
        self,
        node_id: typing.Optional[str] = None,
        environment: typing.Optional[str] = None,
        fact: typing.Optional[filter_complex_search] = None,
    ) -> int:
        query = {}
        self._filter_literal(query, "id", node_id)
        self._filter_complex_search(query, base_attribute="facts", complex_search=fact)
        self._filter_literal(query, "environment", environment)

        result = await self.coll.delete_many(filter=query)
        return result.deleted_count
