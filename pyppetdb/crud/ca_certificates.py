import datetime
import logging
import typing
from typing import List
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.ca.utils import CAUtils
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_certificates import CACertificateGetMulti
from pyppetdb.model.ca_certificates import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.errors import QueryParamValidationError


class CrudCACertificates(CrudMongo):
    def __init__(
        self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection
    ):
        super().__init__(config, log, coll)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [("id", pymongo.ASCENDING), ("space_id", pymongo.ASCENDING)], unique=True
        )
        self.log.info(f"creating {self.resource_type} indices, done")

    async def submit_csr(
        self, space_id: str, certname: str, csr_pem: str, fields: list[str] = []
    ) -> CACertificateGet:
        data = {
            "id": certname,
            "space_id": space_id,
            "status": "requested",
            "csr": csr_pem,
            "created": datetime.datetime.now(datetime.timezone.utc),
        }
        # Upsert: if it exists, overwrite CSR (Puppet behavior)
        await self.coll.update_one(
            {"id": certname, "space_id": space_id}, {"$set": data}, upsert=True
        )
        return await self.get(space_id, certname, fields=fields)

    async def sign(
        self,
        space_id: str,
        certname: str,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        fields: list[str] = [],
    ) -> CACertificateGet:
        cert_data = await self._get(
            query={"id": certname, "space_id": space_id}, fields=[]
        )
        if cert_data["status"] != "requested":
            raise QueryParamValidationError(
                msg="Certificate is not in 'requested' state"
            )

        cert_pem = CAUtils.sign_csr(
            csr_pem=cert_data["csr"].encode(),
            ca_cert_pem=ca_cert_pem,
            ca_key_pem=ca_key_pem,
        )

        info = CAUtils.get_cert_info(cert_pem)
        updates = {"status": "signed", "certificate": cert_pem.decode(), **info}

        await self.coll.update_one(
            {"id": certname, "space_id": space_id}, {"$set": updates}
        )
        return await self.get(space_id, certname, fields=fields)

    async def revoke(
        self, space_id: str, certname: str, fields: list[str] = []
    ) -> CACertificateGet:
        cert_data = await self._get(
            query={"id": certname, "space_id": space_id}, fields=[]
        )
        if cert_data["status"] != "signed":
            raise QueryParamValidationError(
                msg="Only 'signed' certificates can be revoked"
            )

        updates = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc),
        }
        await self.coll.update_one(
            {"id": certname, "space_id": space_id}, {"$set": updates}
        )
        return await self.get(space_id, certname, fields=fields)

    async def get(
        self, space_id: str, certname: str, fields: list[str] = []
    ) -> CACertificateGet:
        _fields = list(fields) if fields else []
        if _fields:
            if "id" not in _fields:
                _fields.append("id")
            if "space_id" not in _fields:
                _fields.append("space_id")
            if "status" not in _fields:
                _fields.append("status")
        result = await self._get(
            query={"id": certname, "space_id": space_id}, fields=_fields
        )
        return CACertificateGet(**result)

    async def delete(self, space_id: str, certname: str) -> None:
        await self._delete(query={"id": certname, "space_id": space_id})

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_revoked_for_spaces(self, space_ids: list[str]) -> list[dict]:
        cursor = self.coll.find(
            {"space_id": {"$in": space_ids}, "status": "revoked"},
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

    async def search_multi_spaces(
        self,
        space_ids: list[str],
        _id: typing.Optional[str] = None,
        status: typing.Optional[CAStatus] = None,
        fingerprint: typing.Optional[str] = None,
        serial_number: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CACertificateGetMulti:
        query = {"space_id": {"$in": space_ids}}
        self._filter_re(query, "id", _id)
        if status:
            query["status"] = status
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

    async def search(
        self,
        _id: typing.Optional[str] = None,
        space_id: typing.Optional[str] = None,
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
        if space_id:
            query["space_id"] = space_id
        if status:
            query["status"] = status
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
