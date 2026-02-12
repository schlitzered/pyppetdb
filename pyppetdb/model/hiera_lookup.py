from typing import Any

from pydantic import BaseModel


class HieraLookupResult(BaseModel):
    data: Any
