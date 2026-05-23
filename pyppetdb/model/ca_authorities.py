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
from pydantic import Field
from pyppetdb.model.common import MetaMulti
from pyppetdb.model.common import Fingerprints
from pyppetdb.model.ca_validation import CAValidationConfig

# CA Status
CAStatus = Literal["active", "revoked"]

filter_literal = Literal[
    "id",
    "parent_id",
    "cn",
    "issuer",
    "serial_number",
    "not_before",
    "not_after",
    "fingerprint",
    "certificate",
    "internal",
    "chain",
    "status",
    "crl",
    "validation_config",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "parent_id",
    "cn",
    "not_before",
    "not_after",
]


class CAAuthorityPost(BaseModel):
    parent_id: Optional[str] = None
    cn: str
    organization: Optional[str] = "PyppetDB"
    organizational_unit: Optional[str] = "CA"
    country: Optional[str] = "DE"
    state: Optional[str] = "Hessen"
    locality: Optional[str] = None
    validity_days: Optional[int] = 3650
    # For external upload
    certificate: Optional[str] = None
    private_key: Optional[str] = None
    external_chain: Optional[List[str]] = None
    validation_config: CAValidationConfig = Field(default_factory=CAValidationConfig)


class CACRL(BaseModel):
    """CRL sub-object for CA authorities"""

    crl_pem: str
    generation: int
    updated_at: datetime
    next_update: datetime
    locked_at: Optional[datetime] = None


class CAAuthorityPostInternal(BaseModel):
    id: str
    parent_id: Optional[str] = None
    cn: str
    issuer: str
    serial_number: str
    not_before: datetime
    not_after: datetime
    fingerprint: Fingerprints
    certificate: str
    private_key_encrypted: str
    internal: bool
    chain: List[str] = []
    status: CAStatus
    revocation_date: Optional[datetime] = None
    crl: Optional[CACRL] = None
    validation_config: CAValidationConfig = Field(default_factory=CAValidationConfig)


class CAAuthorityGet(BaseModel):
    id: Optional[str] = None
    parent_id: Optional[str] = None
    cn: Optional[str] = None
    issuer: Optional[str] = None
    serial_number: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    fingerprint: Optional[Fingerprints] = None
    certificate: Optional[str] = None
    internal: Optional[bool] = None
    chain: Optional[List[str]] = None
    status: Optional[CAStatus] = None
    revocation_date: Optional[datetime] = None
    crl: Optional[CACRL] = None
    validation_config: CAValidationConfig = Field(default_factory=CAValidationConfig)
    private_key_encrypted: Optional[str] = None


class CAAuthorityGetMulti(BaseModel):
    result: List[CAAuthorityGet]
    meta: MetaMulti


class CAAuthorityPut(BaseModel):
    status: Optional[Literal["revoked"]] = None
    validation_config: CAValidationConfig = Field(default_factory=CAValidationConfig)


class CAAuthorityPutInternal(CAAuthorityPut):
    revocation_date: Optional[datetime] = None
