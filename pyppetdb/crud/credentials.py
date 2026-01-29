from datetime import datetime
from datetime import UTC
import logging
import random
import string
import typing
import uuid

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorCollection
from passlib.hash import pbkdf2_sha512
import pymongo

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo

from pyppetdb.errors import CredentialError
from pyppetdb.errors import ResourceNotFound

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.credentials import CredentialGet
from pyppetdb.model.credentials import CredentialGetMulti
from pyppetdb.model.credentials import CredentialPost
from pyppetdb.model.credentials import CredentialPostResult
from pyppetdb.model.credentials import CredentialPut


class CrudCredentials(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
    ):
        super(CrudCredentials, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )

    @staticmethod
    def _create_secret(token) -> str:
        return pbkdf2_sha512.encrypt(str(token), rounds=10, salt_size=32)

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index(
            [("id", pymongo.ASCENDING), ("owner", pymongo.ASCENDING)], unique=True
        )
        self.log.info(f"creating {self.resource_type} indices, done")

    async def check_credential(self, request: Request):
        x_secret = request.headers.get("x-secret", None)
        x_secret_id = request.headers.get("x-secret-id", None)

        if x_secret is None or x_secret_id is None:
            raise CredentialError

        query = {"id": x_secret_id}

        result = await self._get(query=query, fields=["secret", "owner"])

        if not pbkdf2_sha512.verify(x_secret, result["secret"]):
            raise CredentialError

        return result["owner"]

    async def create(
        self,
        owner: str,
        payload: CredentialPost,
    ) -> CredentialPostResult:
        data = payload.model_dump()
        _id = uuid.uuid4()
        secret = "".join(
            random.SystemRandom().choice(string.ascii_letters + string.digits + "_-.")
            for _ in range(128)
        )
        created = datetime.now(UTC)
        data["id"] = str(_id)
        data["secret"] = self._create_secret(str(secret))
        data["created"] = created
        data["owner"] = owner
        await self._create(payload=data, fields=["id"])
        result = {
            "id": str(_id),
            "created": str(created),
            "description": payload.description,
            "secret": str(secret),
        }
        return CredentialPostResult(**result)

    async def delete(self, _id: str, owner: str) -> DataDelete:
        query = {"id": _id, "owner": owner}
        await self._delete(query=query)
        return DataDelete()

    async def delete_all_from_owner(self, owner: str) -> DataDelete:
        query = {"owner": owner}
        try:
            await self._delete(query=query)
        except ResourceNotFound:
            pass
        return DataDelete()

    async def get(self, _id: str, owner: str, fields: list) -> CredentialGet:
        query = {"id": str(_id), "owner": owner}
        result = await self._get(query=query, fields=fields)
        if "created" in result:
            result["created"] = str(result["created"])
        self.log.info(result)
        return CredentialGet(**result)

    async def search(
        self,
        owner: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CredentialGetMulti:
        query = {"owner": owner}

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        for item in result["result"]:
            if "created" in item:
                item["created"] = str(item["created"])
        self.log.info(result)
        return CredentialGetMulti(**result)

    async def update(
        self, _id: str, owner: str, payload: CredentialPut, fields: list
    ) -> CredentialGet:
        query = {"id": _id, "owner": owner}
        data = payload.model_dump()
        result = await self._update(query=query, fields=fields, payload=data)
        if "created" in result:
            result["created"] = str(result["created"])
        return CredentialGet(**result)
