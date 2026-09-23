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

from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.errors import bad_arity
from pyppetdb.pdbquery.errors import bad_operand

SUMMARIZE_BY = {
    "certname": ("certname",),
    "resource": ("resource_type", "resource_title"),
    "containing_class": ("containing_class",),
}
COUNT_BY = ("certname", "resource")
STATUS_BUCKETS = {
    "success": "successes",
    "failure": "failures",
    "noop": "noops",
    "skipped": "skips",
}
EMITTED_FIELDS = ("failures", "successes", "noops", "skips")
COUNT_FIELDS = EMITTED_FIELDS + (
    "intentional_failures",
    "corrective_failures",
    "intentional_successes",
    "corrective_successes",
    "intentional_noops",
    "corrective_noops",
)
COUNTS_FILTER_OPS = ("=", ">", "<", ">=", "<=")
SUMMARIZE_COLUMNS = (
    "certname",
    "resource_type",
    "resource_title",
    "containing_class",
    "status",
)


def parse_summarize_by(raw):
    if not raw:
        raise PuppetDBQueryError(
            "'summarize_by' must be specified. Supported values are "
            f"[{', '.join(sorted(SUMMARIZE_BY))}]."
        )
    fields = []
    for item in str(raw).split(","):
        name = item.strip()
        if name not in SUMMARIZE_BY:
            raise PuppetDBQueryError(
                f"Unsupported value for 'summarize_by': '{name}'. Supported "
                f"values are [{', '.join(sorted(SUMMARIZE_BY))}]."
            )
        fields.append(name)
    return fields


def parse_count_by(raw):
    if raw is None:
        return "resource"
    name = str(raw).strip()
    if name not in COUNT_BY:
        raise PuppetDBQueryError(
            f"Unsupported value for 'count_by': '{name}'. Supported values "
            f"are [{', '.join(COUNT_BY)}]."
        )
    return name


def parse_counts_filter(raw):
    if raw is None:
        return None
    import json

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :counts_filter; expected a JSON array"
        )
    if not isinstance(parsed, list) or not parsed:
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :counts_filter; expected a JSON array"
        )
    validate_counts_filter(parsed)
    return parsed


def validate_counts_filter(node) -> None:
    if not isinstance(node, list) or not node:
        raise PuppetDBQueryError(f"{node!r} is not a valid counts_filter term")
    operator = node[0]
    if operator in ("and", "or"):
        if len(node) < 2:
            raise bad_arity(operator, "at least one argument")
        for child in node[1:]:
            validate_counts_filter(child)
        return
    if operator == "not":
        if len(node) != 2:
            raise bad_arity("not", "exactly one argument")
        validate_counts_filter(node[1])
        return
    if operator not in COUNTS_FILTER_OPS:
        raise PuppetDBQueryError(f"{operator!r} is not a valid counts_filter term")
    if len(node) != 3:
        raise bad_arity(operator, "exactly two arguments")
    field = node[1]
    if field not in COUNT_FIELDS:
        raise PuppetDBQueryError(
            f"'{field}' is not a queryable object for counts_filter. Known "
            f"queryable objects are [{', '.join(COUNT_FIELDS)}]."
        )
    operand = node[2]
    if not isinstance(operand, int) or isinstance(operand, bool):
        raise bad_operand(operator, field, operand, "an integer")


def extract_columns_query(ast):
    if isinstance(ast, list) and ast and ast[0] in ("extract", "from"):
        return ast
    columns = list(SUMMARIZE_COLUMNS)
    if ast is None:
        return ["extract", columns]
    return ["extract", columns, ast]


FIRST_FLAGS = {
    "certname": "first_for_certname",
    "resource": "first_for_resource",
    "containing_class": "first_for_class",
}


def single_report_per_node(ast) -> bool:
    if not isinstance(ast, list) or not ast:
        return False
    if ast[0] == "and":
        return any(single_report_per_node(child) for child in ast[1:])
    if ast[0] != "=" or len(ast) != 3:
        return False
    if ast[1] == "latest_report?":
        return ast[2] is True
    return ast[1] == "report" and isinstance(ast[2], str)


def summary_projection(summarize_by: str, count_by: str, ast) -> dict:
    if not single_report_per_node(ast):
        return {}
    flag = _first_flag(summarize_by, count_by)
    return {flag: f"${flag}"}


def _first_flag(summarize_by: str, count_by: str) -> str:
    if count_by == "certname":
        return FIRST_FLAGS[summarize_by]
    return FIRST_FLAGS["resource"]


def summary_stages(summarize_by: str, count_by: str, ast=None) -> list:
    key_fields = SUMMARIZE_BY[summarize_by]
    group_id = {field: f"$_id.{field}" for field in key_fields}
    if single_report_per_node(ast):
        flag = _first_flag(summarize_by, count_by)
        status_id = {field: f"${field}" for field in key_fields}
        status_id["status"] = "$status"
        buckets = {
            bucket: {"$sum": {"$cond": [{"$eq": ["$_id.status", status]}, "$n", 0]}}
            for status, bucket in STATUS_BUCKETS.items()
        }
        stages = [
            {
                "$group": {
                    "_id": status_id,
                    "n": {"$sum": {"$cond": [{"$eq": [f"${flag}", True]}, 1, 0]}},
                }
            },
            {"$group": {"_id": group_id, **buckets}},
        ]
    else:
        identity = (
            ("certname",)
            if count_by == "certname"
            else ("certname", "resource_type", "resource_title")
        )
        distinct_id = {field: f"${field}" for field in key_fields}
        distinct_id["status"] = "$status"
        distinct_id.update({f"by_{field}": f"${field}" for field in identity})
        buckets = {
            bucket: {"$sum": {"$cond": [{"$eq": ["$_id.status", status]}, 1, 0]}}
            for status, bucket in STATUS_BUCKETS.items()
        }
        stages = [
            {"$group": {"_id": distinct_id}},
            {"$group": {"_id": group_id, **buckets}},
        ]
    stages.append(
        {
            "$project": {
                "_id": 0,
                "subject_type": {"$literal": summarize_by},
                "subject": _subject(summarize_by, key_fields),
                **{field: 1 for field in EMITTED_FIELDS},
            }
        }
    )
    return stages


def _subject(summarize_by: str, key_fields) -> dict:
    if summarize_by == "resource":
        return {
            "type": {"$ifNull": ["$_id.resource_type", None]},
            "title": {"$ifNull": ["$_id.resource_title", None]},
        }
    return {"title": {"$ifNull": [f"$_id.{key_fields[0]}", None]}}


def apply_counts_filter(rows, counts_filter) -> list:
    if not counts_filter:
        return rows
    validate_counts_filter(counts_filter)
    return [row for row in rows if _evaluate(row, counts_filter)]


def _evaluate(row, node) -> bool:
    operator = node[0]
    if operator == "and":
        return all(_evaluate(row, child) for child in node[1:])
    if operator == "or":
        return any(_evaluate(row, child) for child in node[1:])
    if operator == "not":
        return not _evaluate(row, node[1])
    value = _count_value(row, node[1])
    operand = node[2]
    if operator == "=":
        return value == operand
    if operator == ">":
        return value > operand
    if operator == "<":
        return value < operand
    if operator == ">=":
        return value >= operand
    return value <= operand


def _count_value(row, field) -> int:
    value = row.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def aggregate(counts) -> dict:
    totals = {field: 0 for field in EMITTED_FIELDS}
    for row in counts:
        for field in EMITTED_FIELDS:
            if row.get(field):
                totals[field] += 1
    totals["total"] = len(counts)
    return totals
