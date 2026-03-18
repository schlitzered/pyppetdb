from datetime import datetime
from typing import List
from typing import Optional
from typing import Literal
from typing import Dict
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
    created: Optional[datetime] = None
    ca: Optional[str] = None
    ca_chain: List[str] = []


class CACertificateGetMulti(BaseModel):
    result: List[CACertificateGet]
    meta: MetaMulti


class CACertificatePut(BaseModel):
    status: Literal["signed", "revoked"]
