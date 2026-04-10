import pymongo
from pyppetdb.crud.common import CrudMongo
from pyppetdb.model.jobs_nodes_jobs_logs import LogBlobGet


class CrudJobsNodesLogsLogBlobs(CrudMongo):
    async def index_create(self) -> None:
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)

    async def get(self, _id: str, fields: list) -> LogBlobGet:
        query = {"id": _id}
        result = await self._get(query=query, fields=fields)
        return LogBlobGet(**result)
