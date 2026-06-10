# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import datetime
import typing
import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.ca_certificates import (
    CACertificateGet,
    CACertificateGetMulti,
    CACertificatePostInternal,
    CACertificatePutInternal,
)
from pyppetdb.model.ca_certificates import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import DataDelete


class CrudCACertificates(CrudMongo):
    def __init__(
        self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection
    ):
        super().__init__(config, log, coll, schema_model=CACertificateGet)
        self._indices.extend(
            [
                pymongo.IndexModel(
                    [("id", pymongo.ASCENDING)], unique=True, name="idx_id"
                ),
                pymongo.IndexModel(
                    [("serial_number", pymongo.ASCENDING)],
                    unique=True,
                    sparse=True,
                    name="idx_serial_number",
                ),
                pymongo.IndexModel(
                    [
                        ("space_id", pymongo.ASCENDING),
                        ("cert_uniqueness", pymongo.ASCENDING),
                    ],
                    unique=True,
                    name="idx_space_uniqueness",
                ),
                pymongo.IndexModel(
                    [
                        ("space_id", pymongo.ASCENDING),
                        ("status", pymongo.ASCENDING),
                        ("cn", pymongo.ASCENDING),
                    ],
                    name="idx_space_status_cn",
                ),
                pymongo.IndexModel(
                    [
                        ("ca_id", pymongo.ASCENDING),
                        ("status", pymongo.ASCENDING),
                        ("cn", pymongo.ASCENDING),
                    ],
                    name="idx_ca_status_cn",
                ),
                pymongo.IndexModel(
                    [("not_after", pymongo.ASCENDING)],
                    expireAfterSeconds=0,
                    name="ttl_not_after",
                ),
            ]
        )

    async def _create_index(self) -> None:
        await super()._create_index()

    async def update(
        self,
        _id: str,
        payload: CACertificatePutInternal,
        fields: list,
        upsert: bool = False,
        set_on_insert: dict = None,
    ) -> CACertificateGet:
        data = payload.model_dump(exclude_unset=True)
        result = await self._update(
            query={"id": _id},
            payload=data,
            fields=fields,
            upsert=upsert,
            set_on_insert=set_on_insert,
        )
        return CACertificateGet(**result)

    async def upsert_request(
        self,
        space_id: str,
        cn: str,
        payload: CACertificatePutInternal,
        fields: list,
        set_on_insert: dict,
    ) -> CACertificateGet:
        query = {
            "space_id": space_id,
            "cn": cn,
            "status": "requested",
        }
        data = payload.model_dump(exclude_unset=True)
        result = await self._update(
            query=query,
            payload=data,
            fields=fields,
            upsert=True,
            set_on_insert=set_on_insert,
        )
        return CACertificateGet(**result)

    async def create(
        self, _id: str, payload: CACertificatePostInternal, fields: list
    ) -> CACertificateGet:
        data = payload.model_dump()
        data["id"] = _id
        result = await self._create(payload=data, fields=fields)
        return CACertificateGet(**result)

    async def get(
        self,
        _id: str,
        fields: list,
        status: typing.Optional[CAStatus] = None,
        cn: typing.Optional[str] = None,
    ) -> CACertificateGet:
        query = {"id": _id}
        if status:
            query["status"] = status
        if cn:
            query["cn"] = cn
        result = await self._get(query=query, fields=fields)
        return CACertificateGet(**result)

    async def delete(self, _id: str) -> DataDelete:
        await self._delete(query={"id": _id})
        return DataDelete()

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
        await self._delete_many(query=query)

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_revoked_for_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find(
            {"ca_id": {"$eq": ca_id}, "status": "revoked", "serial_number": {"$exists": True}},
            {"serial_number": 1, "revocation_date": 1},
        )
        revoked = []
        async for cert in cursor:
            revoked.append(
                {
                    "serial_number": int(cert["serial_number"]),
                    "revocation_date": cert.get(
                        "revocation_date", datetime.datetime.now(datetime.timezone.utc)
                    ),
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
