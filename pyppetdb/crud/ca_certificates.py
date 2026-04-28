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
            [
                ("space_id", pymongo.ASCENDING),
                ("status", pymongo.ASCENDING),
                ("cn", pymongo.ASCENDING),
            ]
        )
        await self.coll.create_index(
            [
                ("ca_id", pymongo.ASCENDING),
                ("status", pymongo.ASCENDING),
                ("cn", pymongo.ASCENDING),
            ]
        )
        await self.coll.create_index(
            [("not_after", pymongo.ASCENDING)], expireAfterSeconds=0
        )
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

    async def delete_by_cn(
        self,
        space_id: str,
        cn: str,
        status: typing.Optional[CAStatus] = None,
    ) -> None:
        query = {"space_id": space_id, "cn": cn}
        if status:
            query["status"] = status
        await self._delete(query=query)

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
