import atexit
import os
import unittest
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from passlib.hash import pbkdf2_sha512
from pymongo import MongoClient


class IntegrationTestBase(unittest.TestCase):
    _db_name = None
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")
        base = IntegrationTestBase
        if base._db_name is None:
            base._db_name = f"pyppetdb_test_{uuid.uuid4().hex}"
            os.environ["MONGODB_DATABASE"] = base._db_name
        else:
            os.environ["MONGODB_DATABASE"] = base._db_name

        cls._mongo_client = MongoClient(os.environ["MONGODB_URL"])
        cls._db = cls._mongo_client[os.environ["MONGODB_DATABASE"]]

        cls._db["users"].delete_many({})
        cls._db["users_credentials"].delete_many({})

        admin_password = "adminpass"
        admin_hash = pbkdf2_sha512.using(rounds=100000, salt_size=32).hash(
            admin_password
        )
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
        api_secret_hash = pbkdf2_sha512.using(rounds=10, salt_size=32).hash(
            api_secret
        )
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
        atexit.register(base._cleanup)

    @classmethod
    def tearDownClass(cls):
        base = IntegrationTestBase
        if getattr(cls, "_client_ctx", None) is not None:
            cls._client_ctx.__exit__(None, None, None)
            cls._client_ctx = None
        cls._mongo_client.close()

    @classmethod
    def _cleanup(cls):
        base = IntegrationTestBase
        if base._db_name:
            client = MongoClient(os.environ["MONGODB_URL"])
            client.drop_database(base._db_name)
            client.close()
            base._db_name = None

    def setUp(self):
        self.client.cookies.clear()
