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
from typing import Optional

from pyppetdb.pdb.query.ast import parse_timestamp
from pyppetdb.pdb.query.errors import PuppetDBQueryError

GLOBAL_PARAMS = frozenset(
    {
        "optimize_drop_unused_joins",
        "include_facts_expiration",
        "include_package_inventory",
        "explain",
        "origin",
        "timeout",
    }
)
PAGING_PARAMS = frozenset({"query", "limit", "offset", "order_by", "include_total"})
PRETTY_PARAMS = frozenset({"pretty"})
DISTINCT_PARAMS = frozenset(
    {"distinct_resources", "distinct_start_time", "distinct_end_time"}
)
COUNTS_PARAMS = frozenset({"summarize_by", "count_by", "counts_filter"})
TYPICAL_PARAMS = GLOBAL_PARAMS | PAGING_PARAMS | PRETTY_PARAMS
STATUS_PARAMS = GLOBAL_PARAMS | PRETTY_PARAMS
EVENTS_PARAMS = TYPICAL_PARAMS | DISTINCT_PARAMS
ROOT_PARAMS = TYPICAL_PARAMS | {"ast_only"}
EVENT_COUNTS_PARAMS = TYPICAL_PARAMS | DISTINCT_PARAMS | COUNTS_PARAMS
AGGREGATE_EVENT_COUNTS_PARAMS = (
    STATUS_PARAMS | DISTINCT_PARAMS | COUNTS_PARAMS | {"query"}
)
PARAM_SPECS = {
    "typical": (TYPICAL_PARAMS, frozenset()),
    "status": (STATUS_PARAMS, frozenset()),
    "events": (EVENTS_PARAMS, frozenset()),
    "root": (ROOT_PARAMS, frozenset({"query"})),
    "event-counts": (EVENT_COUNTS_PARAMS, frozenset({"summarize_by"})),
    "aggregate-event-counts": (
        AGGREGATE_EVENT_COUNTS_PARAMS,
        frozenset({"summarize_by"}),
    ),
}
ACTIVE_CLAUSE = ["=", "node_state", "active"]
UNRESTRICTED_ROOT_ENTITIES = frozenset({"fact-paths", "environments", "packages"})
TIMEOUT_INT = re.compile(r"^\d+$")
TIMEOUT_FLOAT = re.compile(r"^\d*\.\d+$")


def validate_params(params: dict, spec: str) -> None:
    allowed, required = PARAM_SPECS[spec]
    for name in required:
        if name not in params:
            raise PuppetDBQueryError(f"Missing required query parameter '{name}'")
    for name in params:
        if name not in allowed:
            raise PuppetDBQueryError(f"Unsupported query parameter '{name}'")


def parse_bool(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "true"


def parse_timeout(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise _bad_timeout(raw)
    if isinstance(raw, (int, float)):
        seconds = raw
    else:
        text = str(raw).strip()
        if TIMEOUT_INT.match(text):
            seconds = int(text)
        elif TIMEOUT_FLOAT.match(text):
            seconds = float(text)
        else:
            raise _bad_timeout(raw)
    if seconds < 0:
        raise _bad_timeout(raw)
    return seconds


def _bad_timeout(raw) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f"Query timeout must be non-negative number, not {raw}"
    )


def parse_explain(raw) -> Optional[str]:
    if raw is None:
        return None
    if str(raw) != "analyze":
        raise PuppetDBQueryError(
            f"Unsupported value for 'explain': '{raw}'. Supported values are [analyze]."
        )
    return "analyze"


def parse_distinct(params: dict):
    present = DISTINCT_PARAMS & set(params)
    if not present:
        return None
    if present == DISTINCT_PARAMS:
        if not parse_bool(params["distinct_resources"]):
            return None
        try:
            start = parse_timestamp(str(params["distinct_start_time"]))
            end = parse_timestamp(str(params["distinct_end_time"]))
        except ValueError:
            raise PuppetDBQueryError(
                "query parameters 'distinct_start_time' and 'distinct_end_time' must be "
                f"valid datetime strings: {params['distinct_start_time']} "
                f"{params['distinct_end_time']}"
            )
        return start, end
    if present == {"distinct_start_time", "distinct_end_time"}:
        raise PuppetDBQueryError(
            "'distinct_resources' query parameter must accompany parameters "
            "'distinct_start_time' and 'distinct_end_time'"
        )
    raise PuppetDBQueryError(
        "'distinct_resources' query parameter requires accompanying parameters "
        "'distinct_start_time' and 'distinct_end_time'"
    )


def has_active_criterion(node) -> bool:
    if not isinstance(node, list) or not node:
        return False
    if node[0] == "=" and len(node) == 3:
        field = node[1]
        if field == "node_state" or field == ["node", "active"]:
            return True
    return any(has_active_criterion(child) for child in node[1:])


def root_entity_restricted(entity_name: str) -> bool:
    return entity_name.replace("_", "-") not in UNRESTRICTED_ROOT_ENTITIES
