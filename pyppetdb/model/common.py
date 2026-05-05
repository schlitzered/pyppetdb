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

import re
from typing import Literal
from typing import Set

from pydantic import BaseModel
from pydantic import constr
from pydantic import Field
from typing_extensions import Annotated

sort_order_literal = Literal[
    "ascending",
    "descending",
]


filter_complex_search_pattern = re.compile(
    "(.*):(eq|gt|gte|in|lt|lte|ne|nin|regex):(str|int|float|bool):(.*)"
)
filter_complex_search = Set[constr(pattern=filter_complex_search_pattern.pattern)]


class MetaMulti(BaseModel):
    result_size: Annotated[int, Field(gt=-1)]


class Fingerprints(BaseModel):
    sha256: str
    sha1: str
    md5: str


class DataDelete(BaseModel):
    pass
