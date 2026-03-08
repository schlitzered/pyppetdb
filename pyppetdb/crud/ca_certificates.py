import datetime
import logging
import typing
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.ca_utils import CAUtils
from pyppetdb.model.ca_certificates import (
    CACertificateGet, CACertificateGetMulti, CAStatus
)
from pyppetdb.model.common import sort_order_literal
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces

class CrudCACertificates(CrudMongo):
    def __init__(self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection, 
                 crud_authorities: CrudCAAuthorities, crud_spaces: CrudCASpaces):
        super().__init__(config, log, coll)
        self.crud_authorities = crud_authorities
        self.crud_spaces = crud_spaces

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [("id", pymongo.ASCENDING), ("space_id", pymongo.ASCENDING)],
            unique=True
        )
        self.log.info(f"creating {self.resource_type} indices, done")

    async def submit_csr(self, space_id: str, certname: str, csr_pem: str, fields: list[str] = []) -> CACertificateGet:
        # Check if space exists
        await self.crud_spaces.get(space_id)
        
        data = {
            "id": certname,
            "space_id": space_id,
            "status": "requested",
            "csr": csr_pem,
            "created": datetime.datetime.now(datetime.timezone.utc)
        }
        # Upsert: if it exists, overwrite CSR (Puppet behavior)
        await self.coll.update_one(
            {"id": certname, "space_id": space_id},
            {"$set": data},
            upsert=True
        )
        return await self.get(space_id, certname, fields=fields)

    async def sign(self, space_id: str, certname: str, fields: list[str] = []) -> CACertificateGet:
        cert_data = await self._get(query={"id": certname, "space_id": space_id}, fields=[])
        if cert_data["status"] != "requested":
            raise QueryParamValidationError(msg="Certificate is not in 'requested' state")
            
        space = await self.crud_spaces.get(space_id)
        ca = await self.crud_authorities.get(space.authority_id)
        ca_key = await self.crud_authorities.get_private_key(space.authority_id)
        
        cert_pem = CAUtils.sign_csr(
            csr_pem=cert_data["csr"].encode(),
            ca_cert_pem=ca.certificate.encode(),
            ca_key_pem=ca_key
        )
        
        info = CAUtils.get_cert_info(cert_pem)
        updates = {
            "status": "signed",
            "certificate": cert_pem.decode(),
            **info
        }
        
        await self.coll.update_one(
            {"id": certname, "space_id": space_id},
            {"$set": updates}
        )
        return await self.get(space_id, certname, fields=fields)

    async def revoke(self, space_id: str, certname: str, fields: list[str] = []) -> CACertificateGet:
        cert_data = await self._get(query={"id": certname, "space_id": space_id}, fields=[])
        if cert_data["status"] != "signed":
            raise QueryParamValidationError(msg="Only 'signed' certificates can be revoked")
            
        updates = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc)
        }
        await self.coll.update_one(
            {"id": certname, "space_id": space_id},
            {"$set": updates}
        )
        return await self.get(space_id, certname, fields=fields)

    async def get_crl(self, space_id: str) -> bytes:
        space = await self.crud_spaces.get(space_id)
        ca = await self.crud_authorities.get(space.authority_id)
        ca_key = await self.crud_authorities.get_private_key(space.authority_id)
        
        # Fetch all revoked certs for this space
        revoked_cursor = self.coll.find(
            {"space_id": space_id, "status": "revoked"},
            {"serial_number": 1, "revocation_date": 1}
        )
        revoked_certs = []
        async for cert in revoked_cursor:
            revoked_certs.append({
                "serial_number": int(cert["serial_number"]),
                "revocation_date": cert["revocation_date"]
            })
            
        return CAUtils.generate_crl(
            ca_cert_pem=ca.certificate.encode(),
            ca_key_pem=ca_key,
            revoked_certs=revoked_certs
        )

    async def get(self, space_id: str, certname: str, fields: list[str] = []) -> CACertificateGet:
        result = await self._get(query={"id": certname, "space_id": space_id}, fields=fields)
        return CACertificateGet(**result)

    async def delete(self, space_id: str, certname: str) -> None:
        await self._delete(query={"id": certname, "space_id": space_id})

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

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
