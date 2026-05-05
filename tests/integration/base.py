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
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from pymongo import MongoClient


class IntegrationTestBase(unittest.TestCase):
    _ph = PasswordHasher()

    @classmethod
    def setUpClass(cls):
        from pyppetdb.main import settings

        settings.mongodb.database = "pyppetdb_test"

        cls._mongo_client = MongoClient(settings.mongodb.url)
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
        from pyppetdb.main import lifespan_dev
        from pyppetdb.main import settings
        from pyppetdb.main import version
        from starlette.middleware.sessions import SessionMiddleware

        settings.mongodb.database = "pyppetdb_test"

        app = FastAPI(
            title="pyppetdb all in one dev server",
            version=version,
            lifespan=lifespan_dev,
        )
        app.add_middleware(
            SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
        )

        from pyppetdb.authorize import AuthorizeClientCert
        from unittest.mock import AsyncMock

        AuthorizeClientCert.require_cn = AsyncMock(return_value="test-node")
        AuthorizeClientCert.require_cn_match = AsyncMock(return_value="test-node")
        AuthorizeClientCert.require_cn_trusted = AsyncMock(return_value="test-admin")

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
