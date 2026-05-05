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
from typing import Dict
from pydantic import BaseModel
from pydantic import field_validator
from pydantic import ConfigDict
import re


class PuppetFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    values: Dict[str, Any]
    timestamp: str
    expiration: str

    @field_validator("values")
    @classmethod
    def validate_fact_names(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that all fact names match the pattern ^[a-z][a-z0-9_]*$"""
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for key in v.keys():
            if not pattern.match(key):
                raise ValueError(
                    f"Invalid fact name '{key}': must match pattern ^[a-z][a-z0-9_]*$"
                )
        return v
