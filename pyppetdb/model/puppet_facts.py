from typing import Any
from typing import Dict
from pydantic import BaseModel
from pydantic import field_validator
from pydantic import ConfigDict
import re


class PuppetFacts(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    values: Dict[str, Any]
    timestamp: str
    expiration: str

    @field_validator('values')
    @classmethod
    def validate_fact_names(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that all fact names match the pattern ^[a-z][a-z0-9_]*$"""
        pattern = re.compile(r'^[a-z][a-z0-9_]*$')
        for key in v.keys():
            if not pattern.match(key):
                raise ValueError(
                    f"Invalid fact name '{key}': must match pattern ^[a-z][a-z0-9_]*$"
                )
        return v
