import logging
import typing
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.ca_utils import CAUtils
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost, CAAuthorityGet, CAAuthorityGetMulti
)
from pyppetdb.model.common import sort_order_literal

class CrudCAAuthorities(CrudMongo):
    def __init__(self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection, protector: NodesDataProtector):
        super().__init__(config, log, coll)
        self._protector = protector

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(self, payload: CAAuthorityPost, fields: list[str] = []) -> CAAuthorityGet:
        if payload.certificate and payload.private_key:
            # External upload
            cert_pem = payload.certificate.encode()
            key_pem = payload.private_key.encode()
        elif payload.parent_id:
            # Signed by parent CA
            parent_ca = await self.get(payload.parent_id)
            parent_key = await self.get_private_key(payload.parent_id)
            if not payload.common_name:
                payload.common_name = f"PyppetDB CA {payload.id}"
            cert_pem, key_pem = CAUtils.sign_ca(
                common_name=payload.common_name,
                ca_cert_pem=parent_ca.certificate.encode(),
                ca_key_pem=parent_key,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days
            )
        else:
            # Generate new self-signed
            if not payload.common_name:
                payload.common_name = f"PyppetDB CA {payload.id}"
            cert_pem, key_pem = CAUtils.generate_ca(
                common_name=payload.common_name,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days
            )
        
        info = CAUtils.get_cert_info(cert_pem)
        encrypted_key = self._protector.encrypt_string(key_pem.decode())
        
        data = {
            "id": payload.id,
            "parent_id": payload.parent_id,
            "certificate": cert_pem.decode(),
            "private_key_encrypted": encrypted_key,
            **info
        }
        
        result = await self._create(payload=data, fields=fields)
        return CAAuthorityGet(**result)

    async def get(self, _id: str, fields: list[str] = []) -> CAAuthorityGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CAAuthorityGet(**result)

    async def get_private_key(self, _id: str) -> bytes:
        result = await self._get(query={"id": _id}, fields=["private_key_encrypted"])
        decrypted = self._protector.decrypt_string(result["private_key_encrypted"])
        return decrypted.encode()

    async def search(
        self,
        _id: typing.Optional[str] = None,
        parent_id: typing.Optional[str] = None,
        common_name: typing.Optional[str] = None,
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

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CAAuthorityGetMulti(**result)
