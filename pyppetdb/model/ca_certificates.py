from datetime import datetime
from typing import List, Optional, Literal
from typing import get_args as typing_get_args
from pydantic import BaseModel
from pyppetdb.model.common import MetaMulti

# CA Status
CAStatus = Literal["requested", "signed", "revoked", "expired"]

filter_literal = Literal[
    "id",
    "space_id",
    "status",
    "fingerprint",
    "certificate",
    "csr",
    "not_before",
    "not_after",
    "serial_number",
    "created",
]

filter_list = set(typing_get_args(filter_literal))

sort_literal = Literal[
    "id",
    "status",
    "not_before",
    "not_after",
    "created",
]

class CACertificatePost(BaseModel):
    # This is essentially submitting a CSR
    csr: str

class CACertificateGet(BaseModel):
    id: str  # certname/common_name
    space_id: str
    status: CAStatus
    fingerprint: Optional[str] = None
    certificate: Optional[str] = None
    csr: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    serial_number: Optional[str] = None
    created: Optional[datetime] = None

class CACertificateGetMulti(BaseModel):
    result: List[CACertificateGet]
    meta: MetaMulti

class CACertificateStatusPut(BaseModel):
    desired_state: Literal["signed", "revoked"]
