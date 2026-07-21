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

import atexit
import time
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from pymongo import MongoClient


class IntegrationTestBase(unittest.TestCase):
    _ph = PasswordHasher()

    @classmethod
    def setUpClass(cls):
        from pyppetdb.main import settings

        settings.mongodb.database = "pyppetdb_test"

        cls._mongo_client = MongoClient(
            settings.mongodb.url, serverSelectionTimeoutMS=3000
        )
        try:
            cls._mongo_client.admin.command("ping")
        except Exception as err:
            cls._mongo_client.close()
            raise unittest.SkipTest(
                f"MongoDB not reachable at {settings.mongodb.url}: {err}"
            )
        cls._db = cls._mongo_client[settings.mongodb.database]

        cls._db["users"].delete_many({})
        cls._db["users_credentials"].delete_many({})

        admin_password = "adminpass"
        admin_hash = cls._ph.hash(admin_password)
        cls._db["users"].insert_one(
            {
                "id": "admin",
                "name": "admin",
                "email": "admin@example.com",
                "admin": True,
                "password": admin_hash,
                "backend": "internal",
            }
        )

        api_secret = "test-secret"
        api_secret_hash = cls._ph.hash(api_secret)
        cls._db["users_credentials"].insert_one(
            {
                "id": "test-cred",
                "secret": api_secret_hash,
                "created": datetime.now(timezone.utc),
                "owner": "admin",
                "description": "test credential",
            }
        )

        from fastapi import FastAPI
        from pyppetdb.main import lifespan
        from pyppetdb.main import settings
        from pyppetdb.main import version
        from starlette.middleware.sessions import SessionMiddleware

        settings.mongodb.database = "pyppetdb_test"

        app = FastAPI(
            title="pyppetdb all in one dev server",
            version=version,
            lifespan=lifespan,
        )
        app.add_middleware(
            SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
        )

        from pyppetdb.authorize import AuthorizeClientCert
        from unittest.mock import AsyncMock, patch

        for name, cn in (
            ("require_cn", "test-node"),
            ("require_cn_match", "test-node"),
            ("require_cn_trusted", "test-admin"),
        ):
            patcher = patch.object(
                AuthorizeClientCert, name, AsyncMock(return_value=cn)
            )
            patcher.start()
            cls.addClassCleanup(patcher.stop)

        cls._client_ctx = TestClient(app)
        cls.client = cls._client_ctx.__enter__()
        atexit.register(cls._cleanup)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_client_ctx", None) is not None:
            cls._client_ctx.__exit__(None, None, None)
            cls._client_ctx = None
        cls._mongo_client.close()

    @classmethod
    def _cleanup(cls):
        from pyppetdb.main import settings

        client = MongoClient(settings.mongodb.url)
        client.drop_database(settings.mongodb.database)
        client.close()

    def setUp(self):
        self.client.cookies.clear()

    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def _wait_until(self, predicate, timeout=10.0, interval=0.1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(interval)
        self.fail(f"condition not met within {timeout}s")

    def _make_non_admin(self, permissions=None):
        suffix = uuid.uuid4().hex[:8]
        user_id = f"user-{suffix}"
        cred_id = f"cred-{suffix}"
        team_id = f"team-{suffix}"
        secret = f"secret-{suffix}"
        self._db["users"].insert_one(
            {
                "id": user_id,
                "name": user_id,
                "email": f"{user_id}@example.com",
                "admin": False,
                "backend": "internal",
            }
        )
        self._db["users_credentials"].insert_one(
            {
                "id": cred_id,
                "secret": self._ph.hash(secret),
                "created": datetime.now(timezone.utc),
                "owner": user_id,
                "description": "non-admin test credential",
            }
        )
        self._db["teams"].insert_one(
            {
                "id": team_id,
                "name": team_id,
                "users": [user_id],
                "permissions": list(permissions or []),
            }
        )

        def _cleanup():
            self._db["users"].delete_many({"id": user_id})
            self._db["users_credentials"].delete_many({"id": cred_id})
            self._db["teams"].delete_many({"id": team_id})

        self.addCleanup(_cleanup)
        return SimpleNamespace(
            user_id=user_id,
            cred_id=cred_id,
            team_id=team_id,
            secret=secret,
            headers={"x-secret-id": cred_id, "x-secret": secret},
        )
