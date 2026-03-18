import datetime
import logging
import typing
from typing import List
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.ca.utils import CAUtils
from pyppetdb.model.ca_crls import CACRLGet

class CrudCACRLs(CrudMongo):
    def __init__(self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection):
        super().__init__(config, log, coll)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [("ca_id", pymongo.ASCENDING)],
            unique=True
        )
        self.log.info(f"creating {self.resource_type} indices, done")

    async def get(self, ca_id: str) -> CACRLGet:
        result = await self._get(query={"ca_id": ca_id}, fields=[])
        return CACRLGet(**result)

    async def delete(self, ca_id: str) -> None:
        from pyppetdb.errors import ResourceNotFound
        try:
            await self._delete(query={"ca_id": ca_id})
        except ResourceNotFound:
            pass

    async def _get_raw(self, ca_id: str) -> dict:
        return await self.coll.find_one({"ca_id": ca_id})

    async def update_crl(self, ca_id: str, crl_pem: str, next_update: datetime.datetime, current_counter: int) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        if current_counter == -1:
            # First time creation
            try:
                await self.coll.insert_one({
                    "ca_id": ca_id,
                    "crl_pem": crl_pem,
                    "counter": 1,
                    "updated_at": now,
                    "next_update": next_update,
                    "locked_at": None
                })
                return True
            except pymongo.errors.DuplicateKeyError:
                return False
        else:
            result = await self.coll.update_one(
                {"ca_id": ca_id, "counter": current_counter},
                {
                    "$set": {
                        "crl_pem": crl_pem,
                        "updated_at": now,
                        "next_update": next_update,
                        "locked_at": None
                    },
                    "$inc": {"counter": 1}
                }
            )
            return result.modified_count > 0

    async def sync_crl(self, ca_id: str, ca_cert_pem: bytes, ca_key_pem: bytes,
                       revoked_certs: List[dict]) -> CACRLGet:
        while True:
            raw = await self._get_raw(ca_id)
            current_counter = raw["counter"] if raw else -1
            
            crl_pem, next_update = CAUtils.generate_crl(
                ca_cert_pem=ca_cert_pem,
                ca_key_pem=ca_key_pem,
                revoked_certs=revoked_certs
            )
            
            if await self.update_crl(ca_id, crl_pem.decode(), next_update, current_counter):
                return await self.get(ca_id)

    async def acquire_lock(self, ca_id: str, lock_timeout_minutes: int = 10) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        timeout = now - datetime.timedelta(minutes=lock_timeout_minutes)
        
        result = await self.coll.update_one(
            {
                "ca_id": ca_id,
                "$or": [
                    {"locked_at": None},
                    {"locked_at": {"$lt": timeout}}
                ]
            },
            {"$set": {"locked_at": now}}
        )
        return result.modified_count > 0

    async def unlock(self, ca_id: str) -> None:
        await self.coll.update_one(
            {"ca_id": ca_id},
            {"$set": {"locked_at": None}}
        )

    async def find_expiring_crls(self, threshold_hours: int = 4) -> List[str]:
        threshold = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=threshold_hours)
        cursor = self.coll.find(
            {"next_update": {"$lt": threshold}},
            {"ca_id": 1}
        )
        return [doc["ca_id"] async for doc in cursor]
