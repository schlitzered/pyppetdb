import asyncio
import logging
import socket
from pyppetdb.config import Config
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes
from pyppetdb.ws.hub import WsHub


class JobService:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_node_jobs: CrudJobsNodeJobs,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        hub: WsHub,
    ):
        self._log = log
        self._config = config
        self._crud_node_jobs = crud_node_jobs
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._hub = hub
        self._instance_id = f"{socket.getfqdn()}:{config.app.main.port}"

    async def expire_scheduled_jobs_worker(self) -> None:
        self._log.info("starting scheduled jobs expiration worker")
        while True:
            try:
                leader = await self._crud_pyppetdb_nodes.get_leader()
                if leader == self._instance_id:
                    expired_jobs = await self._crud_node_jobs.expire_scheduled_jobs(
                        timeout_seconds=self._config.jobs.expireSeconds
                    )
                    for job in expired_jobs:
                        self._log.warning(
                            f"Job {job.job_id} for node {job.node_id} expired and marked as failed"
                        )
                        await self._hub.job_finished(
                            node_id=job.node_id,
                            job_id=job.job_id,
                            status="failed",
                            exit_code=1,
                        )
                else:
                    self._log.debug(
                        f"Skipping job expiration, I am not the leader (Leader: {leader}, Me: {self._instance_id})"
                    )
            except Exception as e:
                self._log.error(f"Error in scheduled jobs expiration worker: {e}")
            await asyncio.sleep(delay=60)
