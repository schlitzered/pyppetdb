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

import asyncio
import datetime
import logging
import re
import socket
from concurrent.futures import Executor

from pyppetdb.ca import crypto
from pyppetdb.ca.signer import CASigners
from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes


class CACrl:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_certificates: CrudCACertificates,
        crud_pyppetdb_nodes: CrudPyppetDBNodes,
        signers: CASigners,
        executor: Executor,
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_certificates = crud_certificates
        self._crud_pyppetdb_nodes = crud_pyppetdb_nodes
        self._signers = signers
        self._executor = executor
        self._instance_id = f"{socket.getfqdn()}:{config.app.main.port}"

    @property
    def log(self) -> logging.Logger:
        return self._log

    async def generate(self, ca_id: str) -> None:
        self.log.info(f"Generating CRL for CA '{ca_id}'")
        signer = await self._signers.get(ca_id)
        revoked = await self.revoked_serials(ca_id)
        crl_pem, next_update = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            crypto.generate_crl,
            signer.certificate,
            signer.private_key,
            revoked,
            self._config.ca.crlValidityDays,
        )
        await self._crud_authorities.sync_crl_data(
            ca_id=ca_id, crl_pem=crl_pem.decode(), next_update=next_update
        )

    async def revoked_serials(self, ca_id: str) -> list[dict]:
        fields = ["serial_number", "revocation_date"]
        children = await self._crud_authorities.search(
            parent_id=f"^{re.escape(ca_id)}$", status="revoked", fields=list(fields)
        )
        certificates = await self._crud_certificates.search(
            ca_id=ca_id, status="revoked", fields=list(fields)
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        return [
            {
                "serial_number": int(item.serial_number),
                "revocation_date": item.revocation_date or now,
            }
            for item in [*children.result, *certificates.result]
        ]

    async def refresh_all(self) -> None:
        leader = await self._crud_pyppetdb_nodes.get_leader()
        if leader != self._instance_id:
            self.log.debug(
                f"Skipping CRL refresh, I am not the leader "
                f"(Leader: {leader}, Me: {self._instance_id})"
            )
            return
        self.log.info("I am the leader, refreshing all internal CRLs...")
        authorities = await self._crud_authorities.search(
            internal=True, status="active", fields=["id"]
        )
        for authority in authorities.result:
            try:
                await self.generate(str(authority.id))
            except Exception as err:
                self.log.error(f"Failed to generate CRL for CA '{authority.id}': {err}")

    async def worker(self) -> None:
        while True:
            try:
                await self.refresh_all()
            except Exception as err:
                self.log.error(f"Error in CRL refresh worker: {err}")
            await asyncio.sleep(self._config.ca.crlRefreshInterval)
