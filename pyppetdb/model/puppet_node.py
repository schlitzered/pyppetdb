from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict


class PuppetNode(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    environment: str
    classes: Optional[List[str]] = None
    parameters: Optional[Dict[str, Any]] = None
