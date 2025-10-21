import logging
import typing

from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from passlib.hash import pbkdf2_sha512
import pymongo
import pymongo.errors

from pyppetdb.config import Config

from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.ldap import CrudLdap

from pyppetdb.errors import AuthenticationError
from pyppetdb.errors import BackendError

from pyppetdb.model.common import DataDelete
from pyppetdb.model.common import sort_order_literal
from pyppetdb.model.authenticate import AuthenticatePost
from pyppetdb.model.users import UserGet
from pyppetdb.model.users import UserGetMulti
from pyppetdb.model.users import UserPost
from pyppetdb.model.users import UserPut


class CrudUsers(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        crud_ldap: CrudLdap,
    ):
        super(CrudUsers, self).__init__(
            config=config,
            log=log,
            coll=coll,
        )
        self._crud_ldap = crud_ldap

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    @property
    def crud_ldap(self):
        return self._crud_ldap

    @staticmethod
    def _password(password) -> str:
        return pbkdf2_sha512.encrypt(password, rounds=100000, salt_size=32)

    async def check_credentials(self, credentials: AuthenticatePost) -> str:
        user = credentials.user
        password = credentials.password
        try:
            result = await self._coll.find_one(
                filter={"id": user},
                projection={"password": 1, "backend": 1},
            )
            if not result:
                await self.check_credentials_ldap_and_create_user(
                    credentials=credentials
                )
            elif result["backend"] == "internal":
                if not pbkdf2_sha512.verify(password, result["password"]):
                    raise AuthenticationError
            elif result["backend"] == "ldap":
                try:
                    await self.crud_ldap.check_user_credentials(
                        user=user, password=password
                    )
                except AuthenticationError:
                    raise AuthenticationError
            else:
                self.log.error(
                    f"auth backend mismatch, expected ldap or internal, got: {result['backend']}"
                )
                raise AuthenticationError(
                    msg="backend mismatch, please contact the administrator"
                )
            return user
        except pymongo.errors.ConnectionFailure as err:
            self.log.error(f"backend error: {err}")
            raise BackendError()

    async def check_credentials_ldap_and_create_user(
        self, credentials: AuthenticatePost
    ):
        ldap_user = await self.crud_ldap.check_user_credentials(
            user=credentials.user,
            password=credentials.password,
        )
        result = await self.create_external(
            _id=credentials.user,
            payload=UserPut(
                name=f"{ldap_user['givenName'][0]} {ldap_user['sn'][0]}",
                email=ldap_user["mail"][0],
                admin=False,
            ),
            backend="ldap",
            fields=["_id"],
        )
        return result

    async def create(
        self,
        _id: str,
        payload: UserPost,
        fields: list,
    ) -> UserGet:
        data = payload.model_dump()
        data["id"] = _id
        data["password"] = self._password(payload.password)
        data["backend"] = "internal"
        result = await self._create(payload=data, fields=fields)
        return UserGet(**result)

    async def create_external(
        self,
        _id: str,
        payload: UserPut,
        fields: list,
        backend: str,
    ) -> UserGet:
        data = payload.model_dump()
        data["id"] = _id
        data["backend"] = backend
        result = await self._create(payload=data, fields=fields)
        return UserGet(**result)

    async def delete(
        self,
        _id: str,
    ) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def get(
        self,
        _id: str,
        fields: list,
    ) -> UserGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return UserGet(**result)

    async def resource_exists(
        self,
        _id: str,
    ) -> ObjectId:
        query = {"id": _id}
        return await self._resource_exists(query=query)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> UserGetMulti:
        query = {}
        self._filter_re(query, "id", _id)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return UserGetMulti(**result)

    async def update(
        self,
        _id: str,
        payload: UserPut,
        fields: list,
    ) -> UserGet:
        query = {"id": _id}
        data = payload.model_dump()
        if data["password"] is not None:
            user_orig = await self.get(_id=_id, fields=["backend"])
            if user_orig.backend == "internal":
                data["password"] = self._password(data["password"])
            else:
                data["passwort"] = None

        result = await self._update(query=query, fields=fields, payload=data)
        return UserGet(**result)
