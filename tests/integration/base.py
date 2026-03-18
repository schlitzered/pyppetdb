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

        cls._mongo_client = MongoClient("mongodb://localhost:27017")
        cls._db = cls._mongo_client[f"pyppetdb_test"]

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
        from pyppetdb.main import ORJSONRequest
        from pyppetdb.main import ORJSONResponse
        from pyppetdb.main import lifespan_dev
        from pyppetdb.main import settings
        from pyppetdb.main import version
        from starlette.middleware.sessions import SessionMiddleware
        settings.mongodb.database = f"pyppetdb_test"

        app = FastAPI(
            title="pyppetdb all in one dev server",
            version=version,
            lifespan=lifespan_dev,
            default_response_class=ORJSONResponse,
            request_class=ORJSONRequest,
        )
        app.add_middleware(
            SessionMiddleware, secret_key=settings.app.secretkey, max_age=3600
        )

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
        client = MongoClient("mongodb://localhost:27017")
        client.drop_database(f"pyppetdb_test")
        client.close()

    def setUp(self):
        self.client.cookies.clear()
