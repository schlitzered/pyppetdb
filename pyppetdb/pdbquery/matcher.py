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
from datetime import datetime

_MISSING = object()
_DIGITS = re.compile(r"\d+")


def get_path(row, path: str):
    return _walk(row, path.split("."))


def _walk(current, parts):
    for index, part in enumerate(parts):
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list):
            if part.isdigit() and int(part) < len(current):
                current = current[int(part)]
                continue
            collected = []
            for item in current:
                value = _walk(item, parts[index:])
                if value is not _MISSING:
                    collected.append(value)
            return collected if collected else _MISSING
        else:
            return _MISSING
    return current


def matches(row: dict, query: dict) -> bool:
    if not query:
        return True
    for key, condition in query.items():
        if key == "$and":
            if not all(matches(row, item) for item in condition):
                return False
        elif key == "$or":
            if not any(matches(row, item) for item in condition):
                return False
        elif key == "$nor":
            if any(matches(row, item) for item in condition):
                return False
        elif key == "__never__":
            return False
        else:
            if not _match_field(get_path(row, key), condition):
                return False
    return True


def _match_field(value, condition) -> bool:
    if isinstance(condition, dict) and any(
        key.startswith("$") or key.startswith("__") for key in condition
    ):
        return all(
            _match_operator(value, operator, operand)
            for operator, operand in condition.items()
        )
    return _equals(value, condition)


def _match_operator(value, operator, operand) -> bool:
    if operator == "$in":
        return any(_equals(value, item) for item in operand)
    if operator == "$nin":
        return not any(_equals(value, item) for item in operand)
    if operator == "$ne":
        return not _equals(value, operand)
    if operator == "$regex":
        return _regex(value, operand)
    if operator == "__regex_array__":
        return _regex_array(value, operand, full=False)
    if operator == "__regex_array_full__":
        return _regex_array(value, operand, full=True)
    if operator in ("$gt", "$lt", "$gte", "$lte"):
        return _compare(value, operator, operand)
    if operator == "$exists":
        return (value is not _MISSING) == bool(operand)
    return False


def _equals(value, expected) -> bool:
    if value is _MISSING:
        return expected is None
    if isinstance(value, list) and not isinstance(expected, list):
        return any(_equals(item, expected) for item in value)
    if isinstance(value, datetime) and isinstance(expected, datetime):
        return value == expected
    return value == expected


def _regex(value, pattern) -> bool:
    if isinstance(value, list):
        return any(_regex(item, pattern) for item in value)
    if not isinstance(value, str):
        return False
    return re.search(pattern, value) is not None


def _regex_array(value, patterns, full: bool) -> bool:
    if not isinstance(value, list) or not isinstance(patterns, list):
        return False
    if len(value) != len(patterns):
        return False
    for item, pattern in zip(value, patterns):
        if not _path_element_type_matches(item, pattern):
            return False
        matcher = re.fullmatch if full else re.search
        try:
            if matcher(str(pattern), str(item)) is None:
                return False
        except re.error:
            return False
    return True


def _path_element_type_matches(item, pattern) -> bool:
    item_is_index = isinstance(item, int) and not isinstance(item, bool)
    if isinstance(pattern, int) and not isinstance(pattern, bool):
        return item_is_index
    if isinstance(pattern, str) and _DIGITS.fullmatch(pattern):
        return not item_is_index
    return True


def _compare(value, operator, operand) -> bool:
    if isinstance(value, list):
        return any(_compare(item, operator, operand) for item in value)
    if value is _MISSING or value is None:
        return False
    try:
        if operator == "$gt":
            return value > operand
        if operator == "$lt":
            return value < operand
        if operator == "$gte":
            return value >= operand
        return value <= operand
    except TypeError:
        return False
