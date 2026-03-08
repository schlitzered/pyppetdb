from datetime import datetime
from typing import List, Optional, Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

filter_literal = Literal[
    "id",
    "parent_id",
    "common_name",
    "issuer",
    "serial_number",
    "not_before",
    "not_after",
    "fingerprint",
    "certificate",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "parent_id",
    "common_name",
    "not_before",
    "not_after",
]

class CAAuthorityPost(BaseModel):
    id: str
    parent_id: Optional[str] = None
    common_name: Optional[str] = None
    organization: Optional[str] = "PyppetDB"
    organizational_unit: Optional[str] = "CA"
    country: Optional[str] = "US"
    state: Optional[str] = None
    locality: Optional[str] = None
    validity_days: Optional[int] = 3650
    # For external upload
    certificate: Optional[str] = None
    private_key: Optional[str] = None

class CAAuthorityGet(BaseModel):
    id: str
    parent_id: Optional[str] = None
    common_name: str
    issuer: str
    serial_number: str
    not_before: datetime
    not_after: datetime
    fingerprint: str
    certificate: str
    # Private key is NEVER returned in GET

class CAAuthorityGetMulti(BaseModel):
    result: List[CAAuthorityGet]
    meta: MetaMulti
