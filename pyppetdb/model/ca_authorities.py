from datetime import datetime
from typing import List
from typing import Optional
from typing import Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti
from pyppetdb.model.common import Fingerprints

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


class CACRL(BaseModel):
    """CRL sub-object for CA authorities"""

    crl_pem: str
    generation: int
    updated_at: datetime
    next_update: datetime
    locked_at: Optional[datetime] = None


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


class CAAuthorityGetMulti(BaseModel):
    result: List[CAAuthorityGet]
    meta: MetaMulti


class CAAuthorityPut(BaseModel):
    status: Literal["revoked"]
