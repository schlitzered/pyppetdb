from pyppetdb.crud.common import CrudMongo
import typing
import pymongo
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_spaces import CASpaceGetMulti
from pyppetdb.model.ca_spaces import CASpacePut
from pyppetdb.model.common import sort_order_literal

from motor.motor_asyncio import AsyncIOMotorCollection
from pyppetdb.config import Config
import logging
from pyppetdb.errors import QueryParamValidationError

class CrudCASpaces(CrudMongo):
    def __init__(self, config: Config, log: logging.Logger, coll: AsyncIOMotorCollection, crud_authorities: typing.Any = None):
        super().__init__(config, log, coll)
        self._crud_authorities = crud_authorities

    async def index_create(self) -> None:
        self.log.info(f"creating {self.resource_type} indices")
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        self.log.info(f"creating {self.resource_type} indices, done")

    async def create(self, _id: str, payload: CASpacePost, fields: list[str] = []) -> CASpaceGet:
        data = payload.model_dump()
        data["id"] = _id
        data["authority_id_history"] = []
        result = await self._create(payload=data, fields=fields)
        return CASpaceGet(**result)

    async def get(self, _id: str, fields: list[str] = []) -> CASpaceGet:
        result = await self._get(query={"id": _id}, fields=fields)
        return CASpaceGet(**result)

    async def delete(self, _id: str) -> None:
        if _id == "puppet-ca":
            raise QueryParamValidationError(msg="The 'puppet-ca' space is protected and cannot be deleted")
        await self._delete(query={"id": _id})

    async def update(self, _id: str, payload: CASpacePut, fields: list[str] = []) -> CASpaceGet:
        current = await self.get(_id)
        data = payload.model_dump(exclude_unset=True)
        
        update_op = {}
        
        # Handle authority_id change
        if "authority_id" in data and data["authority_id"] != current.authority_id:
            new_authority_id = data.pop("authority_id")
            update_op.setdefault("$set", {})["authority_id"] = new_authority_id
            
            # If history is NOT manually provided, we push the current one
            if "authority_id_history" not in data:
                update_op["$push"] = {"authority_id_history": current.authority_id}
            else:
                # If history IS manually provided, we ensure current is added to the new list if desired
                # But typically manual modification means full control. 
                # To be safe and predictable, if they provide history, we just use it.
                pass
            
        if data:
            update_op.setdefault("$set", {}).update(data)
            
        if update_op:
            await self.coll.update_one({"id": _id}, update_op)
            
        return await self.get(_id, fields=fields)

    async def count(self, query: dict) -> int:
        return await self.coll.count_documents(query)

    async def remove_ca_from_history(self, ca_id: str) -> None:
        await self.coll.update_many(
            {"authority_id_history": ca_id},
            {"$pull": {"authority_id_history": ca_id}}
        )

    async def search_by_ca(self, ca_id: str) -> list[dict]:
        cursor = self.coll.find({
            "$or": [
                {"authority_id": ca_id},
                {"authority_id_history": ca_id}
            ]
        })
        return await cursor.to_list(length=None)

    async def search(
        self,
        _id: typing.Optional[str] = None,
        authority_id: typing.Optional[str] = None,
        fields: typing.Optional[list] = None,
        sort: typing.Optional[str] = None,
        sort_order: typing.Optional[sort_order_literal] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> CASpaceGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        self._filter_re(query, "authority_id", authority_id)

        result = await self._search(
            query=query,
            fields=fields,
            sort=sort,
            sort_order=sort_order,
            page=page,
            limit=limit,
        )
        return CASpaceGetMulti(**result)
