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

from pyppetdb.helpers.puppetdb import FACTS_INDEX_FIELD
from pyppetdb.helpers.puppetdb import FactsIndexSpec
from pyppetdb.helpers.puppetdb import RESOURCE_PARAM_MAX_VALUE_LEN
from pyppetdb.pdbquery import matcher
from pyppetdb.pdbquery.ast import FilterCompiler
from pyppetdb.pdbquery.ast import check_depth
from pyppetdb.pdbquery.ast import Query
from pyppetdb.pdbquery.ast import parse_query
from pyppetdb.pdbquery.entities import ENTITIES
from pyppetdb.pdbquery.entities import get_entity
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.errors import subquery_too_large
from pyppetdb.pdbquery.errors import unknown_entity
from pyppetdb.pdbquery.errors import unknown_field
from pyppetdb.pdbquery.entities import _UNSET

SUBQUERY_LIMIT = 100000

DEFAULT_FACTS_INDEX = FactsIndexSpec()

_query_timeout = contextvars.ContextVar("pdb_query_timeout", default=0)


class QueryEngine:
    def __init__(
        self,
        log: logging.Logger,
        collections: dict,
        max_query_depth: int = 0,
        max_subquery_depth: int = 0,
        query_timeout: int = 0,
        query_timeout_max: int = 0,
        max_page_size: int = 0,
        facts_index: Optional[FactsIndexSpec] = None,
    ):
        self._log = log
        self._collections = collections
        self._facts_index = facts_index or DEFAULT_FACTS_INDEX
        self._max_query_depth = max_query_depth
        self._max_subquery_depth = max_subquery_depth
        self._query_timeout = query_timeout
        self._query_timeout_max = query_timeout_max
        self._max_page_size = max_page_size

    @property
    def log(self):
        return self._log

    @property
    def facts_index(self) -> FactsIndexSpec:
        return self._facts_index

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
        page_cap: bool = True,
    ):
        check_depth(ast, self._max_query_depth, self._max_subquery_depth)
        seconds = self.effective_timeout(timeout)
        token = _query_timeout.set(seconds)
        try:
            if not seconds:
                return await self._run(entity_name, ast, paging, implicit, page_cap)
            async with asyncio.timeout(seconds):
                return await self._run(entity_name, ast, paging, implicit, page_cap)
        except (TimeoutError, pymongo.errors.ExecutionTimeout):
            raise PuppetDBQueryError(
                f"query exceeded the {seconds}s timeout", status_code=500
            )
        except pymongo.errors.DocumentTooLarge:
            raise subquery_too_large()
        finally:
            _query_timeout.reset(token)

    def _apply_page_cap(self, query: Query) -> None:
        if not self._max_page_size or query.functions:
            return
        if query.limit is None or query.limit > self._max_page_size:
            query.limit = self._max_page_size

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
        page_cap: bool = True,
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
        if page_cap:
            self._apply_page_cap(query)

        if _is_distinct_query(target, query):
            return await self._run_distinct(target, query)

        compiler = FilterCompiler(target, engine=self)
        match = await compiler.compile(query.filter)

        include_total = paging is not None and paging.include_total
        if target.python_expand:
            rows, total = await self._run_python(
                target, query, match, include_total=include_total
            )
        else:
            rows, total = await self._run_mongo(
                target, query, match, include_total=include_total
            )

        if query.functions and not query.group_by and not rows:
            rows, total = [_empty_aggregate_row(query)], 1
        rows = convert_timestamps(target, query, rows)
        if target.scalar_result and not query.columns and not query.functions:
            rows = [row.get(target.scalar_result) for row in rows]
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
        prefilter, exact = (
            build_prefilter_plan(entity, match, self._facts_index)
            if match
            else ({}, True)
        )
        if prefilter:
            head.append({"$match": prefilter})
        element_cond = build_element_filter(entity, match) if match else None
        pinned = build_pinned_keys(entity, match) if match else None
        head.extend(entity.build_stages(element_cond, pinned))
        early_sort = build_early_sort(entity, query)
        if early_sort:
            head.append({"$sort": early_sort})

        collection = self.collection(entity.collection)
        count_filter = None
        if exact and not distinct and not element_cond and not pinned:
            count_filter = _exact_count_filter(entity, prefilter)
        if count_filter is not None and _count_only(query):
            total = await self._count(collection, count_filter)
            return [{query.functions[0].alias: total}], 1

        selected, filter_only = projection_plan(entity, query, match)
        tail = [{"$project": build_projection(entity, selected)}]
        if match:
            tail.append({"$match": _mongo_safe(match)})
        tail.extend(_shape_stages(query))
        distinct = distinct and _groupable(query.columns)
        if distinct:
            tail.extend(_distinct_stages(query.columns))

        total = None
        if include_total and (query.limit is not None or query.offset is not None):
            if count_filter is not None:
                total = await self._count(collection, count_filter)
            else:
                total = await self._count_pipeline(collection, entity, head, match)

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

    async def _count(self, collection, count_filter: dict) -> int:
        options = {}
        timeout = _query_timeout.get()
        if timeout:
            options["maxTimeMS"] = timeout * 1000
        if not count_filter:
            options["hint"] = "_id_"
        return await collection.count_documents(count_filter, **options)

    async def _count_pipeline(self, collection, entity, head: list, match: dict) -> int:
        pipeline = [stage for stage in head if "$sort" not in stage]
        helpers = set()
        _collect_match_columns(match, helpers)
        needed = _resolve_names(entity, helpers)
        if needed:
            pipeline.append({"$project": build_projection(entity, needed)})
        if match:
            pipeline.append({"$match": _mongo_safe(match)})
        pipeline.append({"$count": "count"})
        counted = await collection.aggregate(
            pipeline, **self.aggregate_options
        ).to_list(length=1)
        return counted[0]["count"] if counted else 0

    async def _run_distinct(self, entity, query: Query):
        collection = self.collection(entity.collection)
        values = await collection.distinct(entity.distinct_field)
        names = sorted(
            value
            for value in values
            if isinstance(value, str)
            and not (entity.distinct_top_level and "." in value)
        )
        rows = [{entity.columns[0].name: name} for name in names]
        total = len(rows)
        rows = _python_paging(rows, query)
        if entity.scalar_result:
            rows = [row.get(entity.scalar_result) for row in rows]
        return rows, total

    async def _run_python(
        self, entity, query: Query, match: dict, include_total: bool = False
    ):
        if _is_never(match):
            return [], 0
        collection = self.collection(entity.collection)
        prefilter = (
            build_prefilter(entity, match, self._facts_index) if match else {}
        )
        cursor = collection.find(
            prefilter, projection=_python_projection(entity, match)
        )
        timeout = _query_timeout.get()
        deadline = time.monotonic() + timeout if timeout else None
        if timeout:
            cursor = cursor.max_time_ms(timeout * 1000)
        expander = PYTHON_EXPANDERS[entity.python_expand]
        wanted = None
        if not (
            include_total
            or query.order_by
            or query.functions
            or entity.distinct_rows
        ):
            wanted = (query.offset or 0) + query.limit if query.limit else None
        seen = set() if entity.distinct_rows else None
        rows = []
        batch = []
        async for document in cursor:
            batch.append(document)
            if len(batch) < PYTHON_BATCH_SIZE:
                continue
            rows.extend(
                await asyncio.to_thread(
                    _expand_batch, expander, batch, match, seen, deadline
                )
            )
            batch = []
            if wanted is not None and len(rows) >= wanted:
                break
        if batch:
            rows.extend(
                await asyncio.to_thread(
                    _expand_batch, expander, batch, match, seen, deadline
                )
            )
        total = len(rows)
        rows = _python_shape(rows, query, entity)
        rows = _python_paging(rows, query)
        return rows, total


PYTHON_BATCH_SIZE = 200


def _expand_batch(expander, documents: list, match: dict, seen, deadline) -> list:
    rows = []
    for document in documents:
        if deadline is not None and time.monotonic() > deadline:
            raise PuppetDBQueryError("query exceeded its timeout", status_code=500)
        for row in expander(document):
            if match and not matcher.matches(row, match):
                continue
            if seen is not None:
                key = json.dumps(row, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
            rows.append(row)
    return rows


def _python_projection(entity, match: dict) -> dict:
    projection = dict(PYTHON_PROJECTIONS[entity.python_expand])
    keys = _pinned_node(match, "name") if match else None
    if not keys or len(keys) > MAX_PINNED_KEYS:
        return projection
    if any(not SAFE_KEY.match(key) for key in keys):
        return projection
    projection.pop("facts")
    for key in sorted(keys):
        projection[f"facts.{key}"] = 1
    return projection


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


def _is_distinct_query(entity, query: Query) -> bool:
    if not entity.distinct_field:
        return False
    return not (
        query.filter or query.columns or query.functions or query.group_by
    )


def build_prefilter(entity, match: dict, facts_index=None) -> dict:
    return build_prefilter_plan(entity, match, facts_index)[0]


def build_prefilter_plan(entity, match: dict, facts_index=None) -> tuple:
    if not match:
        return {}, True
    clauses, exact = _prefilter_node(
        entity, match, facts_index or DEFAULT_FACTS_INDEX
    )
    if not clauses:
        return {}, False
    if len(clauses) == 1:
        return clauses[0], exact
    return {"$and": clauses}, exact


def _prefilter_node(entity, node, facts_index) -> tuple:
    if not isinstance(node, dict) or not node:
        return [], False
    clauses = []
    exact = True
    for key, value in node.items():
        if key == "$and":
            for child in value:
                derived, child_exact = _prefilter_node(entity, child, facts_index)
                clauses.extend(derived)
                exact = exact and child_exact
        elif key == "$or":
            branches = []
            branches_exact = True
            for child in value:
                derived, child_exact = _prefilter_node(entity, child, facts_index)
                if not derived:
                    branches = []
                    break
                branches.append(
                    derived[0] if len(derived) == 1 else {"$and": derived}
                )
                branches_exact = branches_exact and child_exact
            if branches:
                clauses.append({"$or": branches})
                exact = exact and branches_exact
            else:
                exact = False
        elif key in ("$nor", "__never__"):
            exact = False
        else:
            leaf, leaf_exact = _prefilter_leaf(entity, key, value, facts_index)
            if leaf:
                clauses.append(leaf)
            exact = exact and bool(leaf) and leaf_exact
    pair = _fact_pair_prefilter(entity, node, facts_index)
    if pair:
        clauses.append(pair)
    return clauses, exact


def _indexable_param_value(value) -> bool:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= RESOURCE_PARAM_MAX_VALUE_LEN
    return False


RESOURCE_PARAMS_FIELD = "params_index"


def _resource_param_prefilter(name: str, condition) -> Optional[dict]:
    field = RESOURCE_PARAMS_FIELD
    if isinstance(condition, dict):
        values = condition.get("$in")
        if (
            len(condition) == 1
            and isinstance(values, list)
            and values
            and all(_indexable_param_value(item) for item in values)
        ):
            return {field: {"$elemMatch": {"n": name, "v": {"$in": values}}}}
        return None
    if _indexable_param_value(condition):
        return {field: {"$elemMatch": {"n": name, "v": condition}}}
    return None


def _facts_index_prefilter(path: str, condition, facts_index) -> Optional[dict]:
    if not facts_index.indexable_path(path):
        return None
    if isinstance(condition, dict):
        values = condition.get("$in")
        if (
            len(condition) == 1
            and isinstance(values, list)
            and values
            and all(facts_index.indexable_value(item) for item in values)
        ):
            return {
                FACTS_INDEX_FIELD: {"$elemMatch": {"p": path, "v": {"$in": values}}}
            }
        return None
    if facts_index.indexable_value(condition):
        return {FACTS_INDEX_FIELD: {"$elemMatch": {"p": path, "v": condition}}}
    return None


def _with_facts_index(
    path: str, condition, direct, direct_exact: bool, facts_index
) -> tuple:
    element = _facts_index_prefilter(path, condition, facts_index)
    if element is None:
        return direct, direct_exact
    if direct is None:
        return element, False
    return {"$and": [element, direct]}, direct_exact


def _fact_pair_prefilter(entity, node, facts_index) -> Optional[dict]:
    spec = entity.fact_pair
    if not spec:
        return None
    names = None
    for condition in _conjunct_leaves(node, spec["name"]):
        found = _pinned_leaf(condition)
        if found is not None and (names is None or len(found) < len(names)):
            names = found
    if not names or len(names) > MAX_PINNED_KEYS:
        return None
    if any("." in name for name in names):
        return None
    clauses = []
    for condition in _conjunct_leaves(node, spec["value"]):
        branches = []
        for name in sorted(names):
            element = _facts_index_prefilter(name, condition, facts_index)
            if element is None:
                branches = []
                break
            branches.append(
                {"$and": [element, {f"{spec['path']}.{name}": condition}]}
            )
        if branches:
            clauses.append(branches[0] if len(branches) == 1 else {"$or": branches})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _conjunct_leaves(node, column_name: str) -> list:
    found = []
    if not isinstance(node, dict):
        return found
    for key, value in node.items():
        if key == "$and":
            for child in value:
                found.extend(_conjunct_leaves(child, column_name))
        elif key == column_name:
            found.append(value)
    return found


def _prefilter_leaf(entity, key: str, condition, facts_index) -> Optional[dict]:
    column = entity.by_name.get(key)
    rest = ""
    if column is None and "." in key:
        head, rest = key.split(".", 1)
        column = entity.by_name.get(head)
        rest = "." + rest
    if column is None or not column.prefilter:
        return None, False

    if column.prefilter_kind == "fact_key":
        if rest:
            return None, False
        if isinstance(condition, str):
            return {f"{column.prefilter}.{condition}": {"$exists": True}}, False
        keys = _pinned_leaf(condition)
        if not keys or len(keys) > MAX_PINNED_KEYS:
            return None, False
        return {
            "$or": [
                {f"{column.prefilter}.{key}": {"$exists": True}}
                for key in sorted(keys)
            ]
        }, False

    if column.prefilter_kind == "node_state":
        if rest or not isinstance(condition, str):
            return None, False
        if condition == "inactive":
            return {column.prefilter: True}, True
        return {column.prefilter: {"$ne": True}}, condition == "active"

    if column.prefilter_kind == "resource_param":
        if not rest:
            return None, False
        return _resource_param_prefilter(rest[1:], condition), False

    path = f"{column.prefilter}{rest}"
    direct, direct_exact = _path_prefilter(path, rest, column, condition)

    if column.prefilter_kind == "fact_value":
        fact_path = path.split(".", 1)[1] if "." in path else ""
        if fact_path:
            return _with_facts_index(
                fact_path, condition, direct, direct_exact, facts_index
            )

    return direct, direct_exact


def _path_prefilter(path: str, rest: str, column, condition) -> tuple:
    identity = bool(rest) or column.prefilter_default is _UNSET
    if isinstance(condition, dict):
        operators = {
            operator: operand
            for operator, operand in condition.items()
            if operator in SOUND_OPERATORS
        }
        if len(operators) != len(condition):
            return None, False
        if not operators:
            return None, False
        return {path: operators}, identity

    if condition is None:
        return None, False
    if not rest and condition == column.prefilter_default:
        return None, False
    return {path: condition}, True


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


def _empty_aggregate_row(query: Query) -> dict:
    return {
        function.alias: 0 if function.name == "count" else None
        for function in query.functions
    }


def _count_only(query: Query) -> bool:
    if len(query.functions) != 1 or query.columns or query.group_by or query.offset:
        return False
    function = query.functions[0]
    return function.name == "count" and not function.column


def _exact_count_filter(entity, prefilter: dict) -> Optional[dict]:
    if not entity.document_rows:
        return None
    clauses = [
        stage["$match"]
        for stage in entity.build_stages(None, None)
        if "$match" in stage
    ]
    if prefilter:
        clauses.append(prefilter)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


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
        keys = {column: _group_key(column) for column in query.group_by or []}
        if keys:
            group_id = {key: f"${column}" for column, key in keys.items()}
        group = {"_id": group_id}
        for function in query.functions:
            group[function.alias] = _accumulator(function)
        stages = [{"$group": group}]
        projection = {"_id": 0}
        for column, key in keys.items():
            projection[column] = f"$_id.{key}"
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


def _group_key(column: str) -> str:
    return column if "." not in column else column.replace(".", "__")


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
