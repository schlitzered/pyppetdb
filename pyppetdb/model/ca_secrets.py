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

# The character set allowed for CA secret ids. Kept in sync with the reference
# grammar in pyppetdb.ca.secret_resolver so every id can be referenced as
# "$secrets[<id>]" without ambiguity.
CA_SECRET_ID_PATTERN = r"^[A-Za-z0-9_-]+$"

filter_literal = Literal[
    "id",
    "description",
    "created",
    "updated",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "created",
    "updated",
]


class CASecretPost(BaseModel):
    secret: str
    description: Optional[str] = None


class CASecretPut(BaseModel):
    secret: Optional[str] = None
    description: Optional[str] = None


class CASecretPostInternal(BaseModel):
    id: str
    secret_encrypted: str
    description: Optional[str] = None
    created: datetime
    updated: datetime


class CASecretPutInternal(BaseModel):
    secret_encrypted: Optional[str] = None
    description: Optional[str] = None
    updated: Optional[datetime] = None


class CASecretGet(BaseModel):
    # Deliberately never exposes the secret value (neither cleartext nor the
    # encrypted representation). Secrets are write-only via the API.
    id: Optional[str] = None
    description: Optional[str] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None


class CASecretGetMulti(BaseModel):
    result: List[CASecretGet]
    meta: MetaMulti
