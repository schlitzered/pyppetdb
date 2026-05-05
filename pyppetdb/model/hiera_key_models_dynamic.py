# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
