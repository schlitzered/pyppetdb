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
from concurrent.futures import Executor

from pyppetdb.ca import crypto
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.model.ca_authorities import CASigner
from pyppetdb.model.ca_authorities import SignerSource


class CASigners:
    def __init__(self, crud_authorities: CrudCAAuthorities, executor: Executor):
        self._crud_authorities = crud_authorities
        self._executor = executor

    @staticmethod
    def load(source: SignerSource) -> CASigner:
        certificate_pem, private_key_pem = source
        return CASigner(
            certificate=crypto.load_certificate(certificate_pem.encode()),
            private_key=crypto.load_private_key(private_key_pem),
            source=source,
        )

    async def get(self, ca_id: str) -> CASigner:
        signer = await self._crud_authorities.get_signer(ca_id)
        if signer is not None:
            return signer
        source = await self._crud_authorities.get_signer_source(ca_id)
        signer = await asyncio.get_running_loop().run_in_executor(
            self._executor, self.load, source
        )
        await self._crud_authorities.store_signer(ca_id, signer)
        return signer
