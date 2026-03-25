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
        # Serial number is globally unique (id field)
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        # Index for querying by space and CN
        await self.coll.create_index(
            [("space_id", pymongo.ASCENDING), ("cn", pymongo.ASCENDING)]
        )
        # Index for querying by CA
        await self.coll.create_index([("ca_id", pymongo.ASCENDING)])
        self.log.info(f"creating {self.resource_type} indices, done")

    async def submit_csr(
        self,
        space_id: str,
        csr_pem: str,
        ca_id: str,
        fields: list,
    ) -> CACertificateGet:
        """Submit a CSR. Updates existing pending CSR if present."""
        # Extract CN from CSR
        csr_info = CAUtils.get_csr_info(csr_pem.encode())
        cn = csr_info["cn"]

        # Check if a pending CSR already exists for this CN in this space
        existing_csr = await self.coll.find_one(
            {"space_id": space_id, "cn": cn, "status": "requested"}
        )

        if existing_csr:
            self.log.info(
                f"Updating existing pending CSR for CN '{cn}' in space '{space_id}'"
            )
            temp_id = existing_csr["id"]
            await self.coll.update_one(
                {"_id": existing_csr["_id"]},
                {
                    "$set": {
                        "ca_id": ca_id,
                        "csr": csr_pem,
                        "created": datetime.datetime.now(datetime.timezone.utc),
                    }
                },
            )
        else:
            # Generate random integer for the ID (will be used as serial number when signed)
            import uuid

            new_id = str(uuid.uuid4().int)

            data = {
                "id": new_id,
                "space_id": space_id,
                "ca_id": ca_id,
                "cn": cn,
                "status": "requested",
                "csr": csr_pem,
                "created": datetime.datetime.now(datetime.timezone.utc),
            }

            await self.coll.insert_one(data)
            temp_id = new_id

        result = await self._get(query={"id": temp_id}, fields=fields)
        return CACertificateGet(**result)

    async def sign(
        self,
        space_id: str,
        cn: str,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        fields: list,
    ) -> CACertificateGet:
        """Sign a CSR identified by space_id and CN. Uses the existing ID as serial number."""
        # Find the pending CSR by space_id and CN with status "requested"
        cert_data = await self.coll.find_one(
            {"space_id": space_id, "cn": cn, "status": "requested"}
        )
        if not cert_data:
            raise QueryParamValidationError(
                msg=f"No pending CSR found for CN '{cn}' in space '{space_id}'"
            )

        serial = cert_data["id"]

        cert_pem = CAUtils.sign_csr(
            csr_pem=cert_data["csr"].encode(),
            ca_cert_pem=ca_cert_pem,
            ca_key_pem=ca_key_pem,
            serial_number=int(serial),
        )

        info = CAUtils.get_cert_info(cert_pem)

        # Update the document with cert info
        updates = {"status": "signed", "certificate": cert_pem.decode(), **info}

        await self.coll.update_one({"_id": cert_data["_id"]}, {"$set": updates})

        # Return the signed certificate
        result = await self._get(query={"id": serial}, fields=fields)
        return CACertificateGet(**result)

    async def revoke(self, _id: str, fields: list) -> CACertificateGet:
        """Revoke a certificate by its serial number."""
        cert_data = await self._get(query={"id": _id}, fields=[])
        if cert_data["status"] != "signed":
            raise QueryParamValidationError(
                msg="Only 'signed' certificates can be revoked"
            )

        updates = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc),
        }
        await self.coll.update_one({"id": _id}, {"$set": updates})
        result = await self._get(query={"id": _id}, fields=fields)
        return CACertificateGet(**result)

    async def get(self, _id: str, fields: list) -> CACertificateGet:
        """Get a certificate by its serial number (ID)."""
        result = await self._get(query={"id": _id}, fields=fields)
        return CACertificateGet(**result)

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

    async def search(
        self,
        _id: typing.Optional[str] = None,
        space_id: typing.Optional[str] = None,
        ca_id: typing.Optional[str] = None,
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
        if ca_id:
            query["ca_id"] = ca_id
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
