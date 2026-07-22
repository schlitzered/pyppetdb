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

import asyncio
import datetime
import logging
from typing import Optional
from typing import Protocol

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_certificates import (
    CACertificateGet,
    CACertificateGetMulti,
    CACertificatePostInternal,
    CACertificatePutInternal,
)
from pyppetdb.model.ca_certificates import CAStatus
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.common import DataDelete


class CacheInvalidationListener(Protocol):
    def invalidate_serial(self, serial: str) -> None: ...

    def invalidate_object_id(self, object_id: str) -> None: ...


class CertRevocationWatcher:
    def __init__(self, log: logging.Logger, coll: AsyncIOMotorCollection):
        self._log = log
        self._coll = coll
        self._listeners: list[CacheInvalidationListener] = []
        self._initialized = False

    def add_listener(self, listener: CacheInvalidationListener) -> None:
        self._listeners.append(listener)

    async def run(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        asyncio.create_task(self._watch_changes())

    def _invalidate_serial(self, serial: str) -> None:
        for listener in self._listeners:
            try:
                listener.invalidate_serial(serial)
            except Exception as e:
                self._log.error(
                    f"Cert revocation listener failed for serial '{serial}': {e}"
                )

    def _invalidate_object_id(self, object_id: str) -> None:
        for listener in self._listeners:
            try:
                listener.invalidate_object_id(object_id)
            except Exception as e:
                self._log.error(
                    f"Cert revocation listener failed for _id '{object_id}': {e}"
                )

    def _handle_change(self, change: dict) -> None:
        operation = change.get("operationType")
        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if not doc:
                return
            if doc.get("status") == "revoked":
                serial = doc.get("id")
                if serial is not None:
                    self._invalidate_serial(serial)
        elif operation == "delete":
            self._invalidate_object_id(str(change["documentKey"]["_id"]))

    async def _watch_changes(self) -> None:
        try:
            async with self._coll.watch(full_document="updateLookup") as change_stream:
                self._log.info(
                    "Change stream watcher started for cert revocation cache"
                )
                async for change in change_stream:
                    self._handle_change(change)
        except Exception as e:
            self._log.error(f"Error in cert revocation change stream: {e}")
            await asyncio.sleep(5)
            asyncio.create_task(self._watch_changes())


class CrudCACertificates(CrudMongo):
    def __init__(
        self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection
    ):
        super().__init__(config, log, coll, schema_model=CACertificateGet)
        self._revocation_watcher = CertRevocationWatcher(log=log, coll=coll)
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

    def add_revocation_listener(self, listener: CacheInvalidationListener) -> None:
        self._revocation_watcher.add_listener(listener)

    async def get_internal_object_id(
        self, serial: str, cn: str, status: str = "signed"
    ) -> str:
        doc = await self.coll.find_one(
            {"id": serial, "cn": cn, "status": status}, {"_id": 1}
        )
        if not doc:
            raise ResourceNotFound(details=f"Certificate '{serial}' not found")
        return str(doc["_id"])

    async def _create_index(self) -> None:
        await super()._create_index()
        await self._revocation_watcher.run()

    async def update(
        self,
        _id: str,
        payload: CACertificatePutInternal,
        fields: list,
        upsert: bool = False,
        set_on_insert: Optional[dict] = None,
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
        status: Optional[CAStatus] = None,
        cn: Optional[str] = None,
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
        fields: list,
        status: Optional[CAStatus] = None,
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
        status: Optional[CAStatus] = None,
    ) -> None:
        query = {"space_id": space_id, "cn": cn}
        if status:
            query["status"] = status
        await self._delete_many(query=query)

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def get_revoked_for_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find(
            {
                "ca_id": {"$eq": ca_id},
                "status": "revoked",
                "serial_number": {"$exists": True},
            },
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
        _id: Optional[str] = None,
        space_id: Optional[str] = None,
        ca_id: Optional[str] = None,
        cn: Optional[str] = None,
        status: Optional[CAStatus] = None,
        fingerprint: Optional[str] = None,
        serial_number: Optional[str] = None,
        fields: Optional[list] = None,
        sort: Optional[str] = None,
        sort_order: Optional[sort_order_literal] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
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
