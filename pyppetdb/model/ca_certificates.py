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

from datetime import datetime
from typing import List
from typing import Optional
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti
from pyppetdb.model.common import Fingerprints

# CA Status
CAStatus = Literal["requested", "signed", "revoked", "expired"]

filter_literal = Literal[
    "id",
    "ca_id",
    "cn",
    "space_id",
    "status",
    "fingerprint",
    "certificate",
    "csr",
    "not_before",
    "not_after",
    "serial_number",
    "created",
    "ca",
    "ca_chain",
    "sans",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "ca_id",
    "cn",
    "status",
    "not_before",
    "not_after",
    "created",
]


class CACertificateGet(BaseModel):
    id: Optional[str] = None
    ca_id: Optional[str] = None
    cn: Optional[str] = None
    space_id: Optional[str] = None
    status: Optional[CAStatus] = None
    fingerprint: Optional[Fingerprints] = None
    certificate: Optional[str] = None
    csr: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    serial_number: Optional[str] = None
    created: Optional[datetime] = None
    cert_uniqueness: Optional[str] = None
    ca: Optional[str] = None
    ca_chain: List[str] = []
    sans: List[str] = []


class CACertificateGetMulti(BaseModel):
    result: List[CACertificateGet]
    meta: MetaMulti


class CACertificatePut(BaseModel):
    status: Literal["signed", "revoked"]
