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

import json
from typing import Any
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from pyppetdb.pdb.query.ast import Query
from pyppetdb.pdb.query.errors import PuppetDBQueryError

VALID_ORDERS = ("asc", "desc")


class Paging(BaseModel):
    order_by: Optional[List[Any]] = Field(default=None)
    limit: Optional[int] = None
    offset: Optional[int] = None
    include_total: bool = False

    def apply(self, query: Query) -> None:
        if self.order_by is not None:
            query.order_by = self.order_by
        if self.limit is not None:
            query.limit = self.limit
        if self.offset is not None:
            query.offset = self.offset


def parse_paging(params) -> Paging:
    return Paging(
        order_by=_parse_order_by(params.get("order_by")),
        limit=_parse_int("limit", params.get("limit"), allow_zero=False),
        offset=_parse_int("offset", params.get("offset"), allow_zero=True),
        include_total=_parse_bool("include_total", params.get("include_total")),
    )


def _parse_order_by(raw) -> Optional[list]:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :order_by; expected a JSON array of maps"
        )
    if not isinstance(parsed, list):
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :order_by; expected a JSON array of maps"
        )
    order = []
    for entry in parsed:
        if not isinstance(entry, dict) or "field" not in entry:
            raise PuppetDBQueryError(
                f"Illegal value '{raw}' for :order_by; expected a JSON array of maps"
            )
        direction = str(entry.get("order", "asc")).lower()
        if direction not in VALID_ORDERS:
            raise PuppetDBQueryError(
                f"Illegal value '{entry.get('order')}' for :order_by; "
                "expected 'asc' or 'desc'"
            )
        order.append((entry["field"], 1 if direction == "asc" else -1))
    return order


def _parse_int(name: str, raw, allow_zero: bool) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(str(raw))
    except ValueError:
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :{name}; expected a positive non-zero integer"
        )
    if str(raw).strip() != str(value):
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :{name}; expected a positive non-zero integer"
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :{name}; expected a positive non-zero integer"
        )
    return value


def _parse_bool(name: str, raw) -> bool:
    if raw is None:
        return False
    text = str(raw).lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise PuppetDBQueryError(
        f"Illegal value '{raw}' for :{name}; expected a boolean"
    )
