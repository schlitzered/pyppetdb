from typing import Any
from typing import Dict
from pydantic import BaseModel
from pydantic import StrictStr


class PuppetDBFacts(BaseModel):
    certname: str
    values: Dict[StrictStr, Any]
    environment: str
    producer_timestamp: str
    producer: str
