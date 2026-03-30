from typing import Any

from pydantic import BaseModel, StrictStr


class HieraKeyModelDynamicPost(BaseModel):
    description: StrictStr = None
    model: dict[str, Any]
