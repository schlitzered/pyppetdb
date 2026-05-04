from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import StrictStr
from pydantic import field_validator


class HieraKeyModelSchema(BaseModel):
    title: StrictStr
    type: Literal["object"]
    required: list[Literal["data"]]
    properties: dict[Literal["data"], dict[str, Any]]

    @field_validator("required")
    @classmethod
    def validate_required(
        cls,
        v: list[str],
    ) -> list[str]:
        if v != ["data"]:
            raise ValueError("required must be exactly ['data']")
        return v

    @field_validator("properties")
    @classmethod
    def validate_properties(
        cls,
        v: dict[str, Any],
    ) -> dict[str, Any]:
        if list(v.keys()) != ["data"]:
            raise ValueError("properties must contain exactly one key: 'data'")
        return v


class HieraKeyModelDynamicPost(BaseModel):
    description: StrictStr = None
    model: HieraKeyModelSchema
