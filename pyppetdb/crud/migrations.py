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

import datetime
import logging
import typing

from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo.errors

MIGRATIONS_COLLECTION = "schema_migrations"

Migration = typing.Callable[..., typing.Awaitable[None]]


class SchemaMigrator:
    def __init__(
        self,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        migrations: list[Migration],
    ):
        self._log = log
        self._coll = coll
        self._migrations = migrations

    @property
    def _ledger(self) -> AsyncIOMotorCollection:
        return self._coll.database[MIGRATIONS_COLLECTION]

    async def version(self) -> int:
        entry = await self._ledger.find_one({"_id": self._coll.name})
        return int(entry["version"]) if entry else 0

    async def run(self) -> int:
        if not self._migrations:
            return 0
        current = await self.version()
        latest = len(self._migrations)
        if current > latest:
            self._log.warning(
                f"schema version {current} of {self._coll.name} is newer than "
                f"the {latest} migrations this code knows, leaving it alone"
            )
            return current
        for version in range(current + 1, latest + 1):
            migration = self._migrations[version - 1]
            self._log.info(
                f"migrating {self._coll.name} to schema version {version} "
                f"({migration.__name__})"
            )
            await self._run_transactional(migration)
            await self._ledger.update_one(
                {"_id": self._coll.name},
                {
                    "$max": {"version": version},
                    "$set": {"updated": datetime.datetime.now(datetime.timezone.utc)},
                },
                upsert=True,
            )
        return latest

    async def _run_transactional(self, migration: Migration) -> None:
        try:
            session = await self._coll.database.client.start_session()
        except (pymongo.errors.OperationFailure, pymongo.errors.ConfigurationError):
            await migration(session=None)
            return
        async with session:
            try:
                async with session.start_transaction():
                    await migration(session=session)
            except pymongo.errors.OperationFailure as err:
                if err.code != 20:
                    raise
                self._log.debug(
                    f"transactions not supported for {self._coll.name}, "
                    "migrating without"
                )
                await migration(session=None)
