import datetime
import logging
import typing
from typing import List
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.ca.utils import CAUtils
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CACRL
from pyppetdb.model.ca_authorities import CAStatus
from pyppetdb.model.common import sort_order_literal

from pyppetdb.errors import QueryParamValidationError


class CrudCAAuthorities(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        protector: NodesDataProtector,
    ):
        super().__init__(config, log, coll)
        self._protector = protector

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(
        self, _id: str, payload: CAAuthorityPost, fields: list
    ) -> CAAuthorityGet:
        if payload.certificate and payload.private_key:
            # External upload
            internal = False
            cert_pem = payload.certificate.encode()
            key_pem = payload.private_key.encode()
            chain = payload.external_chain or []
        elif payload.parent_id:
            # Signed by parent CA
            internal = True
            parent_ca = await self.get(
                payload.parent_id, fields=["certificate", "chain"]
            )
            parent_key = await self.get_private_key(payload.parent_id)
            if not payload.common_name:
                payload.common_name = f"PyppetDB CA {_id}"
            cert_pem, key_pem = CAUtils.sign_ca(
                common_name=payload.common_name,
                ca_cert_pem=parent_ca.certificate.encode(),
                ca_key_pem=parent_key,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days,
            )
            # Chain is parent cert + parent chain
            chain = [parent_ca.certificate] + parent_ca.chain
        else:
            # Generate new self-signed
            internal = True
            if not payload.common_name:
                payload.common_name = f"PyppetDB CA {_id}"
            cert_pem, key_pem = CAUtils.generate_ca(
                common_name=payload.common_name,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days,
            )
            chain = []

        info = CAUtils.get_cert_info(cert_pem)
        encrypted_key = self._protector.encrypt_string(key_pem.decode())

        data = {
            "id": _id,
            "parent_id": payload.parent_id,
            "certificate": cert_pem.decode(),
            "private_key_encrypted": encrypted_key,
            "internal": internal,
            "chain": chain,
            "status": "active",
            **info,
        }

        # Initialize initial CRL (empty, no revoked certs yet) for internal CAs
        if internal:
            crl_pem, next_update = CAUtils.generate_crl(
                ca_cert_pem=cert_pem, ca_key_pem=key_pem, revoked_certs=[]
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            data["crl"] = {
                "crl_pem": crl_pem.decode(),
                "generation": 1,
                "updated_at": now,
                "next_update": next_update,
                "locked_at": None,
            }

        result = await self._create(payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def get(self, _id: str, fields: list) -> CAAuthorityGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CAAuthorityGet(**result)

    async def delete(self, _id: str) -> None:
        await self._delete(query={"id": _id})

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_private_key(self, _id: str) -> bytes:
        result = await self._get(query={"id": _id}, fields=["private_key_encrypted"])
        decrypted = self._protector.decrypt_string(result["private_key_encrypted"])
        return decrypted.encode()

    async def revoke(self, _id: str) -> CAAuthorityGet:
        updates = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc),
        }
        await self.coll.update_one({"id": _id}, {"$set": updates})
        return await self.get(_id, fields=["status", "revocation_date"])

    async def get_revoked(self, parent_id: str) -> list[dict]:
        cursor = self.coll.find(
            {"parent_id": parent_id, "status": "revoked"},
            {"serial_number": 1, "revocation_date": 1},
        )
        revoked = []
        async for ca in cursor:
            revoked.append(
                {
                    "serial_number": int(ca["serial_number"]),
                    "revocation_date": ca["revocation_date"],
                }
            )
        return revoked

    async def search(
        self,
        _id: typing.Optional[str] = None,
        parent_id: typing.Optional[str] = None,
        common_name: typing.Optional[str] = None,
        fingerprint: typing.Optional[str] = None,
        internal: typing.Optional[bool] = None,
        status: typing.Optional[CAStatus] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CAAuthorityGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "parent_id", parent_id)
        self._filter_re(query, "common_name", common_name)
        self._filter_re(query, "fingerprint.sha256", fingerprint)
        if internal is not None:
            query["internal"] = internal
        if status:
            query["status"] = status

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CAAuthorityGetMulti(**result)

    async def sync_crl(
        self,
        ca_id: str,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        revoked_certs: List[dict],
    ) -> CACRL:
        """Generate and update CRL for a CA. CRL must already exist."""
        crl_pem, next_update = CAUtils.generate_crl(
            ca_cert_pem=ca_cert_pem,
            ca_key_pem=ca_key_pem,
            revoked_certs=revoked_certs,
        )

        while True:
            # Get current CA document
            ca_doc = await self.coll.find_one({"id": ca_id}, {"crl": 1})
            if not ca_doc:
                raise Exception(f"CA {ca_id} not found")
            if "crl" not in ca_doc:
                raise Exception(f"CA {ca_id} has no CRL (external CA?)")

            current_generation = ca_doc["crl"]["generation"]
            now = datetime.datetime.now(datetime.timezone.utc)

            # Update with generation check to prevent race conditions
            result = await self.coll.update_one(
                {"id": ca_id, "crl.generation": current_generation},
                {
                    "$set": {
                        "crl.crl_pem": crl_pem.decode(),
                        "crl.updated_at": now,
                        "crl.next_update": next_update,
                        "crl.locked_at": None,
                        "crl.generation": current_generation + 1,
                    }
                },
            )
            if result.modified_count > 0:
                # Get updated CRL
                updated = await self.coll.find_one({"id": ca_id}, {"crl": 1})
                return CACRL(**updated["crl"])

    async def lock_crl_acquire(
        self,
        ca_id: str,
        lock_timeout_minutes: int = 10,
    ) -> bool:
        """Acquire lock for CRL update"""
        now = datetime.datetime.now(datetime.timezone.utc)
        timeout = now - datetime.timedelta(minutes=lock_timeout_minutes)

        result = await self.coll.update_one(
            {
                "id": ca_id,
                "$or": [
                    {"crl.locked_at": None},
                    {"crl.locked_at": {"$lt": timeout}},
                ],
            },
            {"$set": {"crl.locked_at": now}},
        )
        return result.modified_count > 0

    async def lock_crl_release(self, ca_id: str) -> None:
        """Release lock for CRL update"""
        await self.coll.update_one({"id": ca_id}, {"$set": {"crl.locked_at": None}})

    async def find_expiring_crls(self, threshold_hours: int = 4) -> List[str]:
        """Find CAs with expiring CRLs"""
        threshold = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=threshold_hours
        )
        cursor = self.coll.find(
            {"crl.next_update": {"$lt": threshold}},
            {"id": 1}
        )
        return [doc["id"] async for doc in cursor]
