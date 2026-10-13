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

from typing import List

from pydantic import BaseModel
from pydantic import model_validator

from pyppetdb.ca.secrets import extract_references
from pyppetdb.model.ca_validation import CAValidationConfig


def secret_refs_of(config: CAValidationConfig) -> List[str]:
    return sorted(extract_references(config))


class CASecretRefs(BaseModel):
    secret_refs: List[str] = []

    @model_validator(mode="after")
    def _derive_secret_refs(self):
        if "validation_config" in self.model_fields_set:
            self.secret_refs = secret_refs_of(self.validation_config)
        return self
