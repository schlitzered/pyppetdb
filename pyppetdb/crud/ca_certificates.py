import logging
import typing
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_certificates import CACertificateGetMulti
from pyppetdb.model.ca_certificates import CAStatus
from pyppetdb.model.common import sort_order_literal


class CrudCACertificates(CrudMongo):
    def __init__(
        self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection
    ):
        super().__init__(config, log, coll)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.coll.create_index(
            [("space_id", pymongo.ASCENDING), ("cert_uniqueness", pymongo.ASCENDING)],
            unique=True,
        )
        await self.coll.create_index(
            [("space_id", pymongo.ASCENDING), ("cn", pymongo.ASCENDING)]
        )
        await self.coll.create_index([("ca_id", pymongo.ASCENDING)])
        self.log.info(f"creating {self.resource_type} indices, done")

    async def update(
        self, query: dict, payload: dict, fields: list, upsert: bool = False
    ) -> CACertificateGet:
        result = await self._update(
            query=query, payload=payload, fields=fields, upsert=upsert
        )
        return CACertificateGet(**result)

    async def insert(self, payload: dict, fields: list) -> CACertificateGet:
        result = await self._create(payload=payload, fields=fields)
        return CACertificateGet(**result)

    async def get(self, _id: str, fields: list) -> CACertificateGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CACertificateGet(**result)

    async def get_by_cn(
        self,
        space_id: str,
        cn: str,
        status: typing.Optional[CAStatus] = None,
        fields: typing.Optional[list] = None,
    ) -> CACertificateGet:
        query = {"space_id": space_id, "cn": cn}
        if status:
            query["status"] = status
        result = await self._get(query=query, fields=fields)
        return CACertificateGet(**result)

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_revoked_for_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find(
            {"ca_id": {"$eq": ca_id}, "status": "revoked"},
            {"serial_number": 1, "revocation_date": 1},
        )
        revoked = []
        async for cert in cursor:
            revoked.append(
                {
                    "serial_number": int(cert["serial_number"]),
                    "revocation_date": cert["revocation_date"],
                }
            )
        return revoked

    async def revoke_expired(self) -> list[dict]:
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        query = {
            "status": "signed",
            "not_after": {"$lt": now},
        }
        cursor = self.coll.find(query, {"id": 1, "space_id": 1, "ca_id": 1})
        revoked_info = []
        async for cert in cursor:
            await self.coll.update_one(
                {"_id": cert["_id"]},
                {
                    "$set": {
                        "status": "revoked",
                        "revocation_date": now,
                        "cert_uniqueness": cert["id"],
                    }
                },
            )
            revoked_info.append({"space_id": cert["space_id"], "ca_id": cert["ca_id"]})
        return revoked_info

    async def lock_acquire(self, lock_timeout_minutes: int = 5) -> bool:
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        timeout = now - datetime.timedelta(minutes=lock_timeout_minutes)

        result = await self.coll.update_one(
            {
                "id": "expired_revocation_lock",
                "$or": [
                    {"locked_at": None},
                    {"locked_at": {"$lt": timeout}},
                ],
            },
            {"$set": {"locked_at": now}},
            upsert=True,
        )
        # Note: if it's an upsert it might not count as modified_count > 0 in some cases
        # but with $set and the filter, if it was newly created it should be fine.
        # Wait, if it was upserted, it means it didn't exist, so we got the lock.
        return result.modified_count > 0 or result.upserted_id is not None

    async def lock_release(self) -> None:
        await self.coll.update_one(
            {"id": "expired_revocation_lock"}, {"$set": {"locked_at": None}}
        )

    async def search(
        self,
        _id: typing.Optional[str] = None,
        space_id: typing.Optional[str] = None,
        ca_id: typing.Optional[str] = None,
        cn: typing.Optional[str] = None,
        status: typing.Optional[CAStatus] = None,
        fingerprint: typing.Optional[str] = None,
        serial_number: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CACertificateGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_literal(query, "space_id", space_id)
        self._filter_literal(query, "ca_id", ca_id)
        self._filter_literal(query, "status", status)
        self._filter_re(query, "cn", cn)
        self._filter_re(query, "fingerprint.sha256", fingerprint)
        self._filter_re(query, "serial_number", serial_number)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CACertificateGetMulti(**result)
