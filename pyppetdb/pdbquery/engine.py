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

import asyncio
import contextvars
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

import pymongo.errors

from pyppetdb.pdbquery import matcher
from pyppetdb.pdbquery.ast import FilterCompiler
from pyppetdb.pdbquery.ast import check_depth
from pyppetdb.pdbquery.ast import Query
from pyppetdb.pdbquery.ast import parse_query
from pyppetdb.pdbquery.entities import ENTITIES
from pyppetdb.pdbquery.entities import get_entity
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.errors import unknown_entity
from pyppetdb.pdbquery.errors import unknown_field

SUBQUERY_LIMIT = 100000

_query_timeout = contextvars.ContextVar("pdb_query_timeout", default=0)


class QueryEngine:
    def __init__(
        self,
        log: logging.Logger,
        collections: dict,
        aggregate_cache_ttl: int = 0,
        max_query_depth: int = 0,
        max_subquery_depth: int = 0,
        query_timeout: int = 0,
        query_timeout_max: int = 0,
    ):
        self._log = log
        self._collections = collections
        self._aggregate_cache_ttl = aggregate_cache_ttl
        self._max_query_depth = max_query_depth
        self._max_subquery_depth = max_subquery_depth
        self._query_timeout = query_timeout
        self._query_timeout_max = query_timeout_max
        self._aggregate_cache = {}

    @property
    def log(self):
        return self._log

    @property
    def aggregate_options(self) -> dict:
        options = {"allowDiskUse": True}
        timeout = _query_timeout.get()
        if timeout:
            options["maxTimeMS"] = timeout * 1000
        return options

    def collection(self, name: str):
        collection = self._collections.get(name)
        if collection is None:
            raise PuppetDBQueryError(
                f"no backing collection for '{name}'", status_code=500
            )
        return collection

    @staticmethod
    def entity(name: str):
        entity = get_entity(name)
        if entity is None:
            raise unknown_entity(name, list(ENTITIES))
        return entity

    async def validate(self, entity_name: str, ast) -> Query:
        entity = self.entity(entity_name)
        query = parse_query(entity.name, ast, ENTITIES)
        target = self.entity(query.entity)
        compiler = FilterCompiler(target, engine=self, validate_only=True)
        await compiler.compile(query.filter)
        self._check_columns(target, query)
        return query

    def _cache_key(self, entity, query: Query, paging) -> Optional[str]:
        if not self._aggregate_cache_ttl or not entity.cacheable:
            return None
        if query.filter or query.columns or query.functions:
            return None
        if query.limit or query.offset or query.order_by or query.group_by:
            return None
        if paging is not None and (
            paging.limit or paging.offset or paging.order_by
        ):
            return None
        return entity.name

    @staticmethod
    def _check_columns(entity, query: Query) -> None:
        known = entity.queryable_names()
        for column in query.columns or []:
            if entity.resolve(column)[0] is None:
                raise unknown_field(column, entity.name, known)
        for function in query.functions:
            if function.column and entity.resolve(function.column)[0] is None:
                raise unknown_field(function.column, entity.name, known)
        for column in query.group_by or []:
            if entity.resolve(column)[0] is None:
                raise unknown_field(column, entity.name, known)
        for column, _direction in query.order_by or []:
            if entity.resolve(column)[0] is None:
                raise unknown_field(column, entity.name, known)

    async def run(
        self,
        entity_name: str,
        ast,
        paging=None,
        implicit: Optional[list] = None,
        timeout: Optional[int] = None,
    ):
        check_depth(ast, self._max_query_depth, self._max_subquery_depth)
        seconds = self.effective_timeout(timeout)
        token = _query_timeout.set(seconds)
        try:
            if not seconds:
                return await self._run(entity_name, ast, paging, implicit)
            async with asyncio.timeout(seconds):
                return await self._run(entity_name, ast, paging, implicit)
        except (TimeoutError, pymongo.errors.ExecutionTimeout):
            raise PuppetDBQueryError(
                f"query exceeded the {seconds}s timeout", status_code=500
            )
        finally:
            _query_timeout.reset(token)

    def effective_timeout(self, requested: Optional[int]) -> int:
        seconds = self._query_timeout if requested is None else requested
        if self._query_timeout_max and (
            not seconds or seconds > self._query_timeout_max
        ):
            seconds = self._query_timeout_max
        return max(0, seconds)

    async def _run(
        self,
        entity_name: str,
        ast,
        paging=None,
        implicit: Optional[list] = None,
    ):
        entity = self.entity(entity_name)
        query = parse_query(entity.name, ast, ENTITIES)
        target = self.entity(query.entity)
        if implicit:
            query.filter = _merge_filters(query.filter, implicit)
        self._check_columns(target, query)
        if paging is not None:
            paging.apply(query)
            self._check_columns(target, query)

        cache_key = self._cache_key(target, query, paging)
        if cache_key is not None:
            cached = self._aggregate_cache.get(cache_key)
            if cached is not None and cached[0] > time.monotonic():
                return cached[1], cached[2]

        compiler = FilterCompiler(target, engine=self)
        match = await compiler.compile(query.filter)

        include_total = paging is not None and paging.include_total
        if target.python_expand:
            rows, total = await self._run_python(target, query, match)
        else:
            rows, total = await self._run_mongo(
                target, query, match, include_total=include_total
            )

        rows = convert_timestamps(target, query, rows)
        if target.scalar_result and not query.columns and not query.functions:
            rows = [row.get(target.scalar_result) for row in rows]
        if cache_key is not None:
            self._aggregate_cache[cache_key] = (
                time.monotonic() + self._aggregate_cache_ttl,
                rows,
                total,
            )
        return rows, total

    async def select(self, entity_name: str, columns: list, ast) -> list:
        entity = self.entity(entity_name)
        query = parse_query(entity.name, ast, ENTITIES)
        target = self.entity(query.entity)
        for column in columns:
            if target.resolve(column)[0] is None:
                raise unknown_field(column, target.name, target.queryable_names())
        compiler = FilterCompiler(target, engine=self)
        match = await compiler.compile(query.filter)
        query.columns = columns
        query.limit = query.limit or SUBQUERY_LIMIT

        if target.python_expand:
            rows, _total = await self._run_python(target, query, match)
        else:
            rows, _total = await self._run_mongo(
                target, query, match, distinct=True
            )
        if len(rows) >= query.limit:
            self.log.warning(
                f"subquery on {target.name} hit the {query.limit} row limit, "
                f"results may be incomplete"
            )
        return _distinct_tuples(
            [tuple(row.get(column) for column in columns) for row in rows]
        )

    async def _run_mongo(
        self,
        entity,
        query: Query,
        match: dict,
        include_total: bool = False,
        distinct: bool = False,
    ):
        if _is_never(match):
            return [], 0
        head = []
        prefilter = build_prefilter(entity, match) if match else {}
        if prefilter:
            head.append({"$match": prefilter})
        element_cond = build_element_filter(entity, match) if match else None
        pinned = build_pinned_keys(entity, match) if match else None
        head.extend(entity.build_stages(element_cond, pinned))
        early_sort = build_early_sort(entity, query)
        if early_sort:
            head.append({"$sort": early_sort})

        selected, filter_only = projection_plan(entity, query, match)
        tail = [{"$project": build_projection(entity, selected)}]
        if match:
            tail.append({"$match": _mongo_safe(match)})
        tail.extend(_shape_stages(query))
        distinct = distinct and _groupable(query.columns)
        if distinct:
            tail.extend(_distinct_stages(query.columns))

        total = None
        collection = self.collection(entity.collection)
        if include_total and (query.limit is not None or query.offset is not None):
            counted = await collection.aggregate(
                head + tail + [{"$count": "count"}], **self.aggregate_options
            ).to_list(length=1)
            total = counted[0]["count"] if counted else 0

        early_paging = (
            bool(early_sort)
            and not match
            and not query.functions
            and not distinct
        )
        pipeline = list(head)
        if early_paging:
            pipeline.extend(_offset_limit_stages(query))
        pipeline.extend(tail)
        if not early_paging:
            pipeline.extend(_paging_stages(query, sorted_early=bool(early_sort)))
        if filter_only:
            pipeline.append({"$unset": sorted(filter_only)})
        rows = await collection.aggregate(
            pipeline, **self.aggregate_options
        ).to_list(length=None)
        if not query.functions:
            _fill_missing(rows, selected - filter_only)
        if total is None:
            total = len(rows)
        return rows, total

    async def _run_python(self, entity, query: Query, match: dict):
        if _is_never(match):
            return [], 0
        collection = self.collection(entity.collection)
        prefilter = build_prefilter(entity, match) if match else {}
        cursor = collection.find(
            prefilter, projection=PYTHON_PROJECTIONS[entity.python_expand]
        )
        timeout = _query_timeout.get()
        if timeout:
            cursor = cursor.max_time_ms(timeout * 1000)
        documents = await cursor.to_list(length=None)
        expander = PYTHON_EXPANDERS[entity.python_expand]
        rows = [row for document in documents for row in expander(document)]
        if entity.distinct_rows:
            rows = _distinct(rows)
        rows = [row for row in rows if matcher.matches(row, match)]
        total = len(rows)
        rows = _python_shape(rows, query, entity)
        rows = _python_paging(rows, query)
        return rows, total


def _fill_missing(rows: list, names: set) -> None:
    for row in rows:
        for name in names:
            row.setdefault(name, None)


def _groupable(columns) -> bool:
    return bool(columns) and all("." not in column for column in columns)


def _distinct_stages(columns: list) -> list:
    return [
        {"$group": {"_id": {column: f"${column}" for column in columns}}},
        {"$replaceRoot": {"newRoot": "$_id"}},
    ]


def _distinct_tuples(rows: list) -> list:
    seen = set()
    unique = []
    for row in rows:
        try:
            if row in seen:
                continue
            seen.add(row)
        except TypeError:
            pass
        unique.append(row)
    return unique


def _distinct(rows: list) -> list:
    seen = set()
    unique = []
    for row in rows:
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _merge_filters(existing, implicit: list):
    clauses = list(implicit)
    if existing:
        clauses.append(existing)
    if len(clauses) == 1:
        return clauses[0]
    return ["and"] + clauses


SOUND_OPERATORS = ("$in", "$regex", "$gt", "$lt", "$gte", "$lte")


def projection_plan(entity, query: Query, match: dict):
    requested = _needed_columns(entity, query, match)
    if requested is not None:
        return requested, set()

    visible = {
        column.name
        for column in entity.columns
        if column.projected and not column.virtual
    }
    helpers = set()
    _collect_match_columns(match, helpers)
    helpers.update(column for column, _direction in query.order_by or [])
    filter_only = _resolve_names(entity, helpers) - visible
    return visible | filter_only, filter_only


def build_projection(entity, selected) -> dict:
    projection = {"_id": 0}
    for column in entity.columns:
        if column.virtual or column.name not in selected:
            continue
        projection[column.name] = column.expr
    if len(projection) == 1:
        projection["_row"] = {"$literal": 1}
    return projection


def build_early_sort(entity, query: Query):
    if not query.order_by or query.functions or not entity.document_rows:
        return None
    keys = {}
    for column_name, order in query.order_by:
        path = _storage_path(entity, column_name)
        if path is None:
            return None
        keys[path] = order
    if len(keys) != len(query.order_by):
        return None
    return keys


def _storage_path(entity, column_name: str) -> Optional[str]:
    column = entity.by_name.get(column_name)
    if column is None or column.virtual:
        return None
    expr = column.expr
    if not isinstance(expr, str) or not expr.startswith("$"):
        return None
    path = expr[1:]
    if not path or "$" in path:
        return None
    return path


def _resolve_names(entity, names) -> set:
    resolved = set()
    for name in names:
        column = entity.by_name.get(name)
        if column is None and "." in name:
            column = entity.by_name.get(name.split(".", 1)[0])
        if column is not None and not column.virtual:
            resolved.add(column.name)
    return resolved


def _needed_columns(entity, query: Query, match: dict):
    if not query.columns and not query.functions:
        return None
    needed = set(query.columns or [])
    needed.update(
        function.column for function in query.functions if function.column
    )
    needed.update(query.group_by or [])
    needed.update(column for column, _direction in query.order_by or [])
    _collect_match_columns(match, needed)
    return _resolve_names(entity, needed)


def _collect_match_columns(node, into: set) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in ("$and", "$or", "$nor"):
            for child in value:
                _collect_match_columns(child, into)
        elif not key.startswith("$") and not key.startswith("__"):
            into.add(key)


def build_prefilter(entity, match: dict) -> dict:
    clauses = _prefilter_node(entity, match)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _prefilter_node(entity, node) -> list:
    if not isinstance(node, dict) or not node:
        return []
    clauses = []
    for key, value in node.items():
        if key == "$and":
            for child in value:
                clauses.extend(_prefilter_node(entity, child))
        elif key == "$or":
            branches = []
            for child in value:
                derived = _prefilter_node(entity, child)
                if not derived:
                    branches = []
                    break
                branches.append(
                    derived[0] if len(derived) == 1 else {"$and": derived}
                )
            if branches:
                clauses.append({"$or": branches})
        elif key in ("$nor", "__never__"):
            continue
        else:
            leaf = _prefilter_leaf(entity, key, value)
            if leaf:
                clauses.append(leaf)
    return clauses


def _prefilter_leaf(entity, key: str, condition) -> Optional[dict]:
    column = entity.by_name.get(key)
    rest = ""
    if column is None and "." in key:
        head, rest = key.split(".", 1)
        column = entity.by_name.get(head)
        rest = "." + rest
    if column is None or not column.prefilter:
        return None

    if column.prefilter_kind == "fact_key":
        if rest:
            return None
        if isinstance(condition, str):
            return {f"{column.prefilter}.{condition}": {"$exists": True}}
        keys = _pinned_leaf(condition)
        if not keys or len(keys) > MAX_PINNED_KEYS:
            return None
        return {
            "$or": [
                {f"{column.prefilter}.{key}": {"$exists": True}}
                for key in sorted(keys)
            ]
        }

    if column.prefilter_kind == "node_state":
        if rest or not isinstance(condition, str):
            return None
        if condition == "inactive":
            return {column.prefilter: True}
        return {column.prefilter: {"$ne": True}}

    path = f"{column.prefilter}{rest}"

    if isinstance(condition, dict):
        operators = {
            operator: operand
            for operator, operand in condition.items()
            if operator in SOUND_OPERATORS
        }
        if len(operators) != len(condition):
            return None
        if not operators:
            return None
        return {path: operators}

    if condition is None:
        return None
    if not rest and condition == column.prefilter_default:
        return None
    return {path: condition}


ARRAY_COLUMNS = ("tag", "tags", "containment_path")
SAFE_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
MAX_PINNED_KEYS = 16


def build_pinned_keys(entity, match: dict):
    spec = entity.element_filter
    if not spec or not spec.get("key_path"):
        return None
    column = next(
        (
            item
            for item in entity.columns
            if item.prefilter_kind == "fact_key" and item.prefilter == spec["key_path"]
        ),
        None,
    )
    if column is None:
        return None
    keys = _pinned_node(match, column.name)
    if not keys or len(keys) > MAX_PINNED_KEYS:
        return None
    if any(not SAFE_KEY.match(key) for key in keys):
        return None
    return keys


def _pinned_node(node, column_name: str):
    if not isinstance(node, dict) or not node:
        return None
    pinned = None
    for key, value in node.items():
        if key == "$and":
            for child in value:
                found = _pinned_node(child, column_name)
                if found is not None and (pinned is None or len(found) < len(pinned)):
                    pinned = found
        elif key == "$or":
            union = set()
            for child in value:
                found = _pinned_node(child, column_name)
                if found is None:
                    union = None
                    break
                union |= found
            if union:
                pinned = union if pinned is None else pinned & union
        elif key in ("$nor", "__never__"):
            return None
        elif key == column_name:
            found = _pinned_leaf(value)
            if found is not None and (pinned is None or len(found) < len(pinned)):
                pinned = found
    return pinned


def _pinned_leaf(condition):
    if isinstance(condition, str):
        return {condition}
    if isinstance(condition, dict):
        values = condition.get("$in")
        if isinstance(values, list) and values:
            if all(isinstance(item, str) for item in values):
                return set(values)
    return None


def build_element_filter(entity, match: dict):
    spec = entity.element_filter
    if not spec:
        return None
    if not spec.get("nested"):
        return _element_node(entity, spec, match)
    outer = _element_node(entity, spec, match, level="outer")
    inner = _element_node(entity, spec, match, level="inner")
    if outer is None and inner is None:
        return None
    if inner is not None:
        present = {
            "$gt": [
                {
                    "$size": {
                        "$filter": {
                            "input": {"$ifNull": ["$$item.events", []]},
                            "as": "nested",
                            "cond": inner,
                        }
                    }
                },
                0,
            ]
        }
        outer = present if outer is None else {"$and": [outer, present]}
    return {"outer": outer, "inner": inner}


def _element_node(entity, spec, node, level=None):
    if not isinstance(node, dict) or not node:
        return None
    parts = []
    for key, value in node.items():
        if key == "$and":
            for child in value:
                derived = _element_node(entity, spec, child, level)
                if derived is not None:
                    parts.append(derived)
        elif key == "$or":
            branches = []
            for child in value:
                derived = _element_node(entity, spec, child, level)
                if derived is None:
                    branches = []
                    break
                branches.append(derived)
            if branches:
                parts.append(
                    branches[0] if len(branches) == 1 else {"$or": branches}
                )
        elif key in ("$nor", "__never__"):
            continue
        else:
            leaf = _element_leaf(entity, spec, key, value, level)
            if leaf is not None:
                parts.append(leaf)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


def _element_leaf(entity, spec, key: str, condition, level=None):
    column = entity.by_name.get(key)
    rest = ""
    if column is None and "." in key:
        head, tail = key.split(".", 1)
        column = entity.by_name.get(head)
        rest = "." + tail
    if column is None:
        return None
    if level is None:
        element = entity.element_path(column.name)
        variable = "item"
    else:
        element, variable = _nested_element_path(spec, column, level)
    if element is None:
        return None

    field = f"$${variable}.{element}{rest}"
    is_array = not rest and column.name in ARRAY_COLUMNS

    if isinstance(condition, dict):
        operators = {
            operator: operand
            for operator, operand in condition.items()
            if operator in SOUND_OPERATORS
        }
        if len(operators) != len(condition) or not operators:
            return None
        clauses = []
        for operator, operand in operators.items():
            clause = _element_operator(field, is_array, operator, operand)
            if clause is None:
                return None
            clauses.append(clause)
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    if condition is None:
        return None
    if not rest and condition == column.prefilter_default:
        return None
    if is_array:
        return {"$in": [condition, {"$ifNull": [field, []]}]}
    return {"$eq": [field, condition]}


def _nested_element_path(spec, column, level: str):
    if not column.prefilter:
        return None, None
    nested_prefix = spec["nested_prefix"]
    prefix = spec["prefix"]
    if level == "inner":
        if not column.prefilter.startswith(nested_prefix):
            return None, None
        return column.prefilter[len(nested_prefix):], "nested"
    if not column.prefilter.startswith(prefix):
        return None, None
    if column.prefilter.startswith(nested_prefix):
        return None, None
    return column.prefilter[len(prefix):], "item"


def _element_operator(field: str, is_array: bool, operator: str, operand):
    if operator == "$in":
        if is_array:
            return {
                "$gt": [
                    {
                        "$size": {
                            "$setIntersection": [
                                {"$ifNull": [field, []]},
                                list(operand),
                            ]
                        }
                    },
                    0,
                ]
            }
        return {"$in": [field, list(operand)]}
    if operator == "$regex":
        if is_array:
            return None
        return {
            "$cond": [
                {"$eq": [{"$type": field}, "string"]},
                {"$regexMatch": {"input": field, "regex": operand}},
                False,
            ]
        }
    if operator in ("$gt", "$lt", "$gte", "$lte"):
        if is_array:
            return None
        return {
            "$and": [
                {"$ne": [field, None]},
                {operator: [field, operand]},
            ]
        }
    return None


NEVER_MATCH = {"$expr": {"$eq": [1, 0]}}


def _is_never(match) -> bool:
    return isinstance(match, dict) and "__never__" in match


def _mongo_safe(match: dict):
    if isinstance(match, dict):
        cleaned = {}
        for key, value in match.items():
            if key == "__never__":
                cleaned.update(NEVER_MATCH)
            elif key in ("$and", "$or", "$nor"):
                cleaned[key] = [_mongo_safe(item) for item in value]
            else:
                cleaned[key] = value
        return cleaned
    return match


def _shape_stages(query: Query) -> list:
    if not query.columns and not query.functions:
        return []
    if query.functions:
        group_id = None
        if query.group_by:
            group_id = {column: f"${column}" for column in query.group_by}
        group = {"_id": group_id}
        for function in query.functions:
            group[function.alias] = _accumulator(function)
        stages = [{"$group": group}]
        projection = {"_id": 0}
        for column in query.group_by or []:
            projection[column] = f"$_id.{column}"
        for function in query.functions:
            projection[function.alias] = 1
        for column in query.columns or []:
            if column not in projection:
                projection[column] = f"$_id.{column}"
        return stages + [{"$project": projection}]
    projection = {"_id": 0}
    for column in query.columns:
        projection[column] = 1
    return [{"$project": projection}]


def _accumulator(function):
    if function.name == "count":
        if function.column:
            return {
                "$sum": {
                    "$cond": [{"$eq": [f"${function.column}", None]}, 0, 1]
                }
            }
        return {"$sum": 1}
    if function.name == "sum":
        return {"$sum": f"${function.column}"}
    if function.name == "avg":
        return {"$avg": f"${function.column}"}
    if function.name == "min":
        return {"$min": f"${function.column}"}
    if function.name == "max":
        return {"$max": f"${function.column}"}
    return {"$first": {"$toString": f"${function.column}"}}


def _paging_stages(query: Query, sorted_early: bool = False) -> list:
    stages = []
    if query.order_by and not sorted_early:
        stages.append({"$sort": {column: order for column, order in query.order_by}})
    stages.extend(_offset_limit_stages(query))
    return stages


def _offset_limit_stages(query: Query) -> list:
    stages = []
    if query.offset:
        stages.append({"$skip": query.offset})
    if query.limit:
        stages.append({"$limit": query.limit})
    return stages


def _python_shape(rows: list, query: Query, entity=None) -> list:
    if not query.columns and not query.functions:
        if entity is None:
            return rows
        visible = [
            column.name
            for column in entity.columns
            if column.projected and not column.virtual
        ]
        return [
            {name: row[name] for name in visible if name in row} for row in rows
        ]
    if query.functions:
        groups = {}
        for row in rows:
            key = tuple(row.get(column) for column in query.group_by or [])
            groups.setdefault(key, []).append(row)
        shaped = []
        for key, members in groups.items():
            item = {}
            for index, column in enumerate(query.group_by or []):
                item[column] = key[index]
            for function in query.functions:
                item[function.alias] = _python_accumulate(function, members)
            shaped.append(item)
        return shaped
    return [{column: row.get(column) for column in query.columns} for row in rows]


def _python_accumulate(function, rows: list):
    if function.name == "count":
        if function.column:
            return sum(1 for row in rows if row.get(function.column) is not None)
        return len(rows)
    values = [
        row.get(function.column)
        for row in rows
        if isinstance(row.get(function.column), (int, float))
    ]
    if function.name == "sum":
        return sum(values)
    if function.name == "avg":
        return sum(values) / len(values) if values else None
    if function.name == "min":
        return min(values) if values else None
    if function.name == "max":
        return max(values) if values else None
    first = rows[0].get(function.column) if rows else None
    return None if first is None else str(first)


def _python_paging(rows: list, query: Query) -> list:
    if query.order_by:
        for column, order in reversed(query.order_by):
            rows.sort(
                key=lambda row: _sort_key(row.get(column)),
                reverse=order < 0,
            )
    start = query.offset or 0
    if query.limit:
        return rows[start:start + query.limit]
    return rows[start:]


def _sort_key(value):
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, datetime):
        return (2, value.timestamp())
    return (3, str(value))


def expand_fact_contents(document: dict) -> list:
    facts = document.get("facts")
    if not isinstance(facts, dict):
        return []
    certname = document.get("id")
    environment = document.get("environment")
    state = "inactive" if document.get("disabled") else "active"
    rows = []
    for name, value in facts.items():
        for path, leaf in _walk_fact(value, [name]):
            rows.append(
                {
                    "certname": certname,
                    "environment": environment,
                    "name": name,
                    "path": path,
                    "value": leaf,
                    "node_state": state,
                }
            )
    return rows


def expand_fact_paths(document: dict) -> list:
    facts = document.get("facts")
    if not isinstance(facts, dict):
        return []
    rows = []
    for name, value in facts.items():
        for path, leaf in _walk_fact(value, [name]):
            rows.append(
                {
                    "name": name,
                    "path": path,
                    "type": _fact_type(leaf),
                }
            )
    return rows


def _walk_fact(value, path: list):
    if isinstance(value, dict):
        if not value:
            yield list(path), value
            return
        for key, item in value.items():
            yield from _walk_fact(item, path + [key])
        return
    if isinstance(value, list):
        if not value:
            yield list(path), value
            return
        for index, item in enumerate(value):
            yield from _walk_fact(item, path + [index])
        return
    yield list(path), value


def _fact_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return "json"


PYTHON_EXPANDERS = {
    "fact_contents": expand_fact_contents,
    "fact_paths": expand_fact_paths,
}

PYTHON_PROJECTIONS = {
    "fact_contents": {
        "_id": 0,
        "id": 1,
        "environment": 1,
        "disabled": 1,
        "facts": 1,
    },
    "fact_paths": {"_id": 0, "facts": 1},
}


def convert_timestamps(entity, query: Query, rows: list) -> list:
    fields = output_timestamp_fields(entity, query)
    if not fields:
        return rows
    for row in rows:
        for field in fields:
            value = row.get(field)
            if isinstance(value, datetime):
                row[field] = _iso(value)
    return rows


def output_timestamp_fields(entity, query: Query) -> list:
    def is_timestamp(name):
        column = entity.by_name.get(name)
        return column is not None and column.type == "timestamp"

    if query.functions:
        names = [name for name in query.group_by or [] if is_timestamp(name)]
        for function in query.functions:
            if function.name in ("min", "max") and is_timestamp(function.column):
                names.append(function.alias)
        return names
    if query.columns:
        return [name for name in query.columns if is_timestamp(name)]
    return [
        column.name
        for column in entity.columns
        if column.projected and not column.virtual and column.type == "timestamp"
    ]


def _iso(value: datetime) -> str:
    text = value.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    if value.tzinfo is None:
        return text + "Z"
    return text
