from typing import Any, Optional

from pydantic import BaseModel, StrictStr


class HieraKeyModelDynamicPost(BaseModel):
    description: Optional[StrictStr] = None
    model: dict[str, Any]

