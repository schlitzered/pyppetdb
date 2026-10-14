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
import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pymongo.errors

from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.migrations import MIGRATIONS_COLLECTION
from pyppetdb.crud.migrations import SchemaMigrator


class _Transaction:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        self._session.transactions += 1

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self):
        self.transactions = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def start_transaction(self):
        return _Transaction(self)


class TestSchemaMigrator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.ledger = MagicMock()
        self.ledger.find_one = AsyncMock(return_value=None)
        self.ledger.update_one = AsyncMock()
        self.coll = MagicMock()
        self.coll.name = "things"
        self.coll.database.__getitem__.side_effect = lambda name: {
            MIGRATIONS_COLLECTION: self.ledger
        }[name]
        self.session = _Session()
        self.coll.database.client.start_session = AsyncMock(return_value=self.session)
        self.calls = []

    def _migration(self, name, error=None):
        async def migration(session=None):
            self.calls.append((name, session))
            if error is not None and session is not None:
                raise error

        migration.__name__ = name
        return migration

    def _recorded_versions(self):
        versions = []
        for call in self.ledger.update_one.await_args_list:
            query, update = call.args
            self.assertEqual(query, {"_id": "things"})
            self.assertTrue(call.kwargs["upsert"])
            versions.append(update["$max"]["version"])
        return versions

    async def test_without_migrations_the_ledger_is_not_touched(self):
        result = await SchemaMigrator(self.log, self.coll, []).run()

        self.assertEqual(result, 0)
        self.ledger.find_one.assert_not_awaited()
        self.ledger.update_one.assert_not_awaited()

    async def test_fresh_collection_runs_every_migration_in_order(self):
        migrations = [self._migration("first"), self._migration("second")]

        result = await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(result, 2)
        self.assertEqual(self.calls, [("first", self.session), ("second", self.session)])
        self.assertEqual(self.session.transactions, 2)
        self.assertEqual(self._recorded_versions(), [1, 2])
        self.ledger.find_one.assert_awaited_once_with({"_id": "things"})

    async def test_only_pending_migrations_run(self):
        self.ledger.find_one = AsyncMock(return_value={"_id": "things", "version": 1})
        migrations = [self._migration("first"), self._migration("second")]

        await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual([name for name, _ in self.calls], ["second"])
        self.assertEqual(self._recorded_versions(), [2])

    async def test_current_collection_runs_nothing(self):
        self.ledger.find_one = AsyncMock(return_value={"_id": "things", "version": 2})
        migrations = [self._migration("first"), self._migration("second")]

        result = await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(result, 2)
        self.assertEqual(self.calls, [])
        self.ledger.update_one.assert_not_awaited()

    async def test_newer_schema_than_the_code_is_left_alone(self):
        self.ledger.find_one = AsyncMock(return_value={"_id": "things", "version": 5})
        migrations = [self._migration("first")]

        with self.assertLogs("test", level="WARNING"):
            result = await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(result, 5)
        self.assertEqual(self.calls, [])
        self.ledger.update_one.assert_not_awaited()

    async def test_failing_migration_runs_once_and_is_not_recorded(self):
        error = pymongo.errors.OperationFailure("boom", code=11000)
        migrations = [self._migration("first", error=error), self._migration("second")]

        with self.assertRaises(pymongo.errors.OperationFailure):
            await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(self.calls, [("first", self.session)])
        self.ledger.update_one.assert_not_awaited()

    async def test_without_transactions_the_migration_runs_without_session(self):
        error = pymongo.errors.OperationFailure("no transactions", code=20)
        migrations = [self._migration("first", error=error)]

        await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(self.calls, [("first", self.session), ("first", None)])
        self.assertEqual(self._recorded_versions(), [1])

    async def test_without_sessions_the_migration_runs_without_session(self):
        self.coll.database.client.start_session = AsyncMock(
            side_effect=pymongo.errors.ConfigurationError("no sessions")
        )
        migrations = [self._migration("first")]

        await SchemaMigrator(self.log, self.coll, migrations).run()

        self.assertEqual(self.calls, [("first", None)])
        self.assertEqual(self._recorded_versions(), [1])


class TestCrudMongoMigrations(unittest.IsolatedAsyncioTestCase):
    async def test_crud_without_migrations_skips_the_ledger(self):
        coll = MagicMock()
        coll.name = "plain"
        crud = CrudMongo(MagicMock(), logging.getLogger("test"), coll)

        await crud._migrate()

        coll.database.__getitem__.assert_not_called()

    def test_no_version_index_is_declared(self):
        coll = MagicMock()
        coll.name = "plain"
        crud = CrudMongo(MagicMock(), logging.getLogger("test"), coll)

        self.assertEqual(crud._indices, [])
