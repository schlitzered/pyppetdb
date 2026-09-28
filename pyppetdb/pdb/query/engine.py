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

import pymongo
import pymongo.errors

from pyppetdb.helpers.puppetdb import FACTS_INDEX_FIELD
from pyppetdb.helpers.puppetdb import FactsIndexSpec
from pyppetdb.helpers.puppetdb import RESOURCE_PARAM_MAX_VALUE_LEN
from pyppetdb.helpers.puppetdb import decode_fact_path
from pyppetdb.helpers.puppetdb import walk_fact
from pyppetdb.pdb.query import matcher
from pyppetdb.pdb.query.ast import FilterCompiler
from pyppetdb.pdb.query.ast import TUPLE_IN
from pyppetdb.pdb.query.params import ACTIVE_CLAUSE
from pyppetdb.pdb.query.params import has_active_criterion
from pyppetdb.pdb.query.ast import check_depth
from pyppetdb.pdb.query.ast import Query
from pyppetdb.pdb.query.ast import parse_query
from pyppetdb.pdb.query.entities import ENTITIES
from pyppetdb.pdb.query.entities import get_entity
from pyppetdb.pdb.query.errors import PuppetDBQueryError
from pyppetdb.pdb.query.errors import page_too_large
from pyppetdb.pdb.query.errors import subquery_too_large
from pyppetdb.pdb.query.errors import unknown_entity
from pyppetdb.pdb.query.errors import unknown_field
from pyppetdb.pdb.query.entities import _UNSET

SUBQUERY_LIMIT = 100000
DISTINCT_TYPES = ("string", "integer", "boolean", "timestamp")
TUPLE_FIELD_PREFIX = "__tuple_"

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
        self._index_keys = {}

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
            options["maxTimeMS"] = int(timeout * 1000)
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
        timeout=None,
        restrict_active: bool = False,
        extra_columns: Optional[list] = None,
        distinct_window=None,
        stream: bool = False,
    ):
        return await self._guarded(
            ast,
            timeout,
            lambda: self._run(
                entity_name,
                ast,
                paging,
                implicit,
                restrict_active=restrict_active,
                extra_columns=extra_columns,
                distinct_window=distinct_window,
                stream=stream,
            ),
        )

    async def explain(
        self,
        entity_name: str,
        ast,
        paging=None,
        implicit: Optional[list] = None,
        timeout=None,
        restrict_active: bool = False,
        distinct_window=None,
    ):
        return await self._guarded(
            ast,
            timeout,
            lambda: self._run(
                entity_name,
                ast,
                paging,
                implicit,
                restrict_active=restrict_active,
                distinct_window=distinct_window,
                explain=True,
            ),
        )

    async def group(
        self,
        entity_name: str,
        ast,
        stages: list,
        extra: Optional[dict] = None,
        timeout=None,
        distinct_window=None,
    ):
        return await self._guarded(
            ast,
            timeout,
            lambda: self._group(entity_name, ast, stages, extra, distinct_window),
        )

    async def _guarded(self, ast, timeout: Optional[int], work):
        check_depth(ast, self._max_query_depth, self._max_subquery_depth)
        seconds = self.effective_timeout(timeout)
        token = _query_timeout.set(seconds)
        try:
            if not seconds:
                return await work()
            async with asyncio.timeout(seconds):
                return await work()
        except (TimeoutError, pymongo.errors.ExecutionTimeout):
            raise PuppetDBQueryError(
                f"query exceeded the {seconds}s timeout", status_code=500
            )
        except pymongo.errors.DocumentTooLarge:
            raise subquery_too_large()
        finally:
            _query_timeout.reset(token)

    def _apply_page_cap(self, query: Query) -> Optional[int]:
        if not self._max_page_size or query.functions:
            return None
        if query.limit is None or query.limit > self._max_page_size:
            query.limit = self._max_page_size + 1
            return self._max_page_size
        return None

    def effective_timeout(self, requested):
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
        restrict_active: bool = False,
        extra_columns: Optional[list] = None,
        distinct_window=None,
        explain: bool = False,
        stream: bool = False,
    ):
        entity = self.entity(entity_name)
        query = parse_query(entity.name, ast, ENTITIES)
        target = self.entity(query.entity)
        clauses = list(implicit or [])
        if (
            restrict_active
            and "node_state" in target.by_name
            and not has_active_criterion(query.filter)
        ):
            clauses.append(ACTIVE_CLAUSE)
        if clauses:
            query.filter = _merge_filters(query.filter, clauses)
        self._check_columns(target, query)
        if paging is not None:
            paging.apply(query)
            self._check_columns(target, query)
        stream = (
            stream
            and not explain
            and not target.python_expand
            and not query.functions
            and not _is_distinct_query(target, query)
        )
        cap = None if stream else self._apply_page_cap(query)

        if _is_distinct_query(target, query) and not explain:
            rows, total = await self._run_distinct(target, query)
            return _within_cap(rows, cap), total

        compiler = FilterCompiler(target, engine=self)
        match = await compiler.compile(query.filter)

        include_total = paging is not None and paging.include_total
        if target.python_expand:
            if explain:
                return self._explain_python(target, match)
            rows, total = await self._run_python(
                target, query, match, include_total=include_total
            )
        else:
            rows, total = await self._run_mongo(
                target,
                query,
                match,
                include_total=include_total,
                extra_columns=extra_columns,
                distinct_window=distinct_window,
                explain=explain,
                stream=stream,
            )
            if explain:
                return rows

        scalar = (
            target.scalar_result
            if target.scalar_result and not query.columns and not query.functions
            else None
        )
        if stream:
            rows.scalar = scalar
            return rows, total
        rows = _within_cap(rows, cap)
        if query.functions and not query.group_by and not rows:
            rows, total = [_empty_aggregate_row(query)], 1
        if scalar:
            rows = [row.get(scalar) for row in rows]
        return rows, total

    def _explain_python(self, entity, match: dict) -> list:
        if entity.distinct_source:
            return [{"query plan": {"distinct": entity.collection, "key": entity.distinct_source}}]
        prefilter = build_prefilter(entity, match, self._facts_index) if match else {}
        return [{"query plan": {"find": entity.collection, "filter": prefilter, "expand": entity.python_expand}}]

    async def _group(
        self,
        entity_name: str,
        ast,
        stages: list,
        extra: Optional[dict] = None,
        distinct_window=None,
    ) -> list:
        entity = self.entity(entity_name)
        query = parse_query(entity.name, ast, ENTITIES)
        target = self.entity(query.entity)
        if target.python_expand:
            raise PuppetDBQueryError(
                f"{target.name} cannot be grouped in the database", status_code=500
            )
        self._check_columns(target, query)
        compiler = FilterCompiler(target, engine=self)
        match = await compiler.compile(query.filter)
        if _is_never(match):
            return []
        head, _prefilter, exact, element_cond, pinned = self._pipeline_head(
            target, match, distinct_window
        )
        pipeline = list(head)
        rows_exact = (
            exact
            and element_cond is None
            and pinned is None
            and _document_level(target, match)
        )
        rewritten = _rewrite_to_storage(target, stages) if rows_exact else None
        if rewritten is not None:
            covered = _covering_prefilter(target, _prefilter)
            if covered is not None:
                pipeline = [{"$match": covered}] + pipeline[1 if _prefilter else 0:]
            pipeline.extend(rewritten)
        else:
            selected, _filter_only = projection_plan(target, query, match)
            pipeline.append(
                {"$project": {**build_projection(target, selected), **(extra or {})}}
            )
            if match:
                tuple_fields = {}
                condition = _mongo_safe(match, tuple_fields)
                if tuple_fields:
                    pipeline.append({"$addFields": tuple_fields})
                pipeline.append({"$match": condition})
            pipeline.extend(stages)
        return await self.collection(target.collection).aggregate(
            pipeline, **self.aggregate_options
        ).to_list(length=None)

    def _pipeline_head(self, entity, match: dict, distinct_window=None):
        prefilter, exact = (
            build_prefilter_plan(entity, match, self._facts_index)
            if match
            else ({}, True)
        )
        if distinct_window is not None:
            prefilter = _partition_prefilter(prefilter)
            exact = False
        head = [{"$match": prefilter}] if prefilter else []
        if distinct_window is not None:
            head.extend(_distinct_event_stages(*distinct_window))
        element_cond = build_element_filter(entity, match) if match else None
        pinned = build_pinned_keys(entity, match) if match else None
        head.extend(entity.build_stages(element_cond, pinned))
        return head, prefilter, exact, element_cond, pinned

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
            rows = await self._select_fact_documents(target, query, match)
            if rows is None:
                rows = await self._select_distinct(target, query, match)
            if rows is None:
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

    async def _select_fact_documents(self, entity, query: Query, match: dict):
        spec = entity.fact_pair
        if not spec or not match or len(query.columns) != 1:
            return None
        name = query.columns[0]
        path = _storage_path(entity, name)
        if path is None or not _document_level(entity, {name: 1}):
            return None
        names = None
        rest = []
        for clause in _top_conjuncts(match):
            if set(clause) == {spec["name"]}:
                found = _pinned_leaf(clause[spec["name"]])
                if found is None:
                    return None
                names = found if names is None else names & found
            else:
                rest.append(clause)
        if names is None:
            return None
        if not names:
            return []
        if len(names) > MAX_PINNED_KEYS or any(not SAFE_KEY.match(key) for key in names):
            return None
        remainder = rest[0] if len(rest) == 1 else ({"$and": rest} if rest else {})
        if remainder and not _document_level(entity, remainder):
            return None
        prefilter, exact = (
            build_prefilter_plan(entity, remainder, self._facts_index)
            if remainder
            else ({}, True)
        )
        if not exact:
            return None
        present = [
            {
                "$and": [
                    {f"{FACTS_INDEX_FIELD}.p": key},
                    {f"{spec['path']}.{key}": {"$exists": True}},
                ]
            }
            for key in sorted(names)
        ]
        condition = present[0] if len(present) == 1 else {"$or": present}
        pipeline = [
            {"$match": _and_filters(prefilter, condition)},
            {"$group": {"_id": f"${path}"}},
            {"$match": {"_id": {"$ne": None}}},
            {"$limit": query.limit},
        ]
        rows = await self.collection(entity.collection).aggregate(
            pipeline, **self.aggregate_options
        ).to_list(length=None)
        return [{name: row["_id"]} for row in rows]

    async def _select_distinct(self, entity, query: Query, match: dict):
        if not entity.document_rows or len(query.columns) != 1:
            return None
        name = query.columns[0]
        column = entity.by_name.get(name)
        path = _storage_path(entity, name)
        if column is None or path is None or column.type not in DISTINCT_TYPES:
            return None
        prefilter, exact = (
            build_prefilter_plan(entity, match, self._facts_index)
            if match
            else ({}, True)
        )
        if not exact:
            return None
        clauses = [stage["$match"] for stage in entity.stages]
        if prefilter:
            clauses.append(prefilter)
        pipeline = []
        if clauses:
            pipeline.append(
                {"$match": clauses[0] if len(clauses) == 1 else {"$and": clauses}}
            )
        pipeline.extend(
            [
                {"$group": {"_id": f"${path}"}},
                {"$match": {"_id": {"$ne": None}}},
                {"$limit": query.limit},
            ]
        )
        rows = await self.collection(entity.collection).aggregate(
            pipeline, **self.aggregate_options
        ).to_list(length=None)
        return [{name: row["_id"]} for row in rows]

    async def _run_mongo(
        self,
        entity,
        query: Query,
        match: dict,
        include_total: bool = False,
        distinct: bool = False,
        extra_columns: Optional[list] = None,
        distinct_window=None,
        explain: bool = False,
        stream: bool = False,
    ):
        if _is_never(match):
            return (RowStream.empty() if stream else []), 0
        head, prefilter, exact, element_cond, pinned = self._pipeline_head(
            entity, match, distinct_window
        )
        rows_exact = (
            exact
            and element_cond is None
            and pinned is None
            and _document_level(entity, match)
        )
        early_sort = build_early_sort(entity, query)
        if early_sort is None and rows_exact and not query.functions and not distinct:
            early_sort = build_early_sort(entity, query, document_rows_only=False)
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
        if extra_columns and not query.columns and not query.functions:
            selected = selected | set(extra_columns)
        tail = [{"$project": build_projection(entity, selected)}]
        if match:
            tuple_fields = {}
            condition = _mongo_safe(match, tuple_fields)
            if tuple_fields:
                tail.append({"$addFields": tuple_fields})
                filter_only = filter_only | set(tuple_fields)
            tail.append({"$match": condition})
        tail.extend(_shape_stages(query))
        distinct = distinct and _groupable(query.columns)
        if distinct:
            tail.extend(_distinct_stages(query.columns))

        total = None
        if include_total and (
            stream or query.limit is not None or query.offset is not None
        ):
            if count_filter is not None:
                total = await self._count(collection, count_filter)
            else:
                total = await self._count_pipeline(collection, entity, head, match)

        early_paging = (
            bool(early_sort)
            and rows_exact
            and not query.functions
            and not distinct
        )
        pipeline = list(head)
        if early_paging and match and query.offset and not (
            query.offset >= DEEP_OFFSET
            and await self._skips_on_index_keys(collection, early_sort, prefilter)
        ):
            if query.limit:
                pipeline.append({"$limit": query.offset + query.limit})
            pipeline.extend(_skip_behind_match(tail, query.offset))
        elif early_paging:
            pipeline.extend(_offset_limit_stages(query))
            pipeline.extend(tail)
        else:
            pipeline.extend(tail)
        if not early_paging:
            pipeline.extend(_paging_stages(query, sorted_early=bool(early_sort)))
        if not query.functions:
            pipeline.extend(
                _null_fill_stages(
                    set(query.columns) if query.columns else selected - filter_only
                )
            )
        if filter_only:
            pipeline.append({"$unset": sorted(filter_only)})
        if explain:
            plan = await collection.database.command(
                "explain",
                {"aggregate": collection.name, "pipeline": pipeline, "cursor": {}},
                verbosity="executionStats",
            )
            plan.pop("$clusterTime", None)
            plan.pop("operationTime", None)
            return [{"query plan": plan}], 1
        cursor = collection.aggregate(pipeline, **self.aggregate_options)
        if stream:
            first = await cursor.to_list(length=STREAM_BATCH_SIZE)
            return RowStream(cursor, first), total
        rows = await cursor.to_list(length=None)
        if total is None:
            total = len(rows)
        return rows, total

    async def _skips_on_index_keys(self, collection, sort: dict, prefilter: dict) -> bool:
        fields = set()
        _collect_filter_fields(prefilter, fields)
        wanted = list(sort.items())
        for keys in await self._collection_index_keys(collection):
            prefix = keys[: len(wanted)]
            if [field for field, _ in prefix] != [field for field, _ in wanted]:
                continue
            same = all(key == order for (_, key), (_, order) in zip(prefix, wanted))
            flipped = all(key == -order for (_, key), (_, order) in zip(prefix, wanted))
            if (same or flipped) and fields <= {field for field, _ in keys}:
                return True
        return False

    async def _collection_index_keys(self, collection) -> list:
        cached = self._index_keys.get(collection.name)
        if cached is not None and time.monotonic() - cached[0] < INDEX_KEYS_TTL:
            return cached[1]
        keys = []
        async for index in collection.list_indexes():
            if index.get("partialFilterExpression"):
                continue
            spec = list(index["key"].items())
            if all(isinstance(direction, int) for _, direction in spec):
                keys.append(spec)
        self._index_keys[collection.name] = (time.monotonic(), keys)
        return keys

    async def _count(self, collection, count_filter: dict) -> int:
        options = {}
        timeout = _query_timeout.get()
        if timeout:
            options["maxTimeMS"] = int(timeout * 1000)
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
            tuple_fields = {}
            condition = _mongo_safe(match, tuple_fields)
            if tuple_fields:
                pipeline.append({"$addFields": tuple_fields})
            pipeline.append({"$match": condition})
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
        if entity.distinct_source:
            rows = await self._expand_distinct(entity, match)
        else:
            rows = await self._expand_documents(entity, query, match, include_total)
        total = len(rows)
        rows = _python_shape(rows, query, entity)
        rows = _python_paging(rows, query)
        return rows, total

    async def _expand_distinct(self, entity, match: dict) -> list:
        collection = self.collection(entity.collection)
        options = {}
        timeout = _query_timeout.get()
        if timeout:
            options["maxTimeMS"] = int(timeout * 1000)
        values = await collection.distinct(entity.distinct_source, **options)
        expander = PYTHON_EXPANDERS[entity.python_expand]
        return [
            row
            for row in expander(values)
            if not match or matcher.matches(row, match)
        ]

    async def _expand_documents(
        self, entity, query: Query, match: dict, include_total: bool
    ) -> list:
        collection = self.collection(entity.collection)
        prefilter = (
            build_prefilter(entity, match, self._facts_index) if match else {}
        )
        keys = _pinned_node(match, "name") if match else None
        candidates = await self._fact_path_candidates(entity, match)
        if candidates is not None:
            keys, entries = candidates
            if not entries:
                return []
            if len(entries) <= MAX_PATH_PREFILTER:
                prefilter = _and_filters(
                    prefilter, {entity.path_source: {"$in": entries}}
                )
        cursor = collection.find(
            prefilter, projection=_python_projection(entity, keys)
        )
        timeout = _query_timeout.get()
        deadline = time.monotonic() + timeout if timeout else None
        if timeout:
            cursor = cursor.max_time_ms(timeout * 1000)
        expander = PYTHON_EXPANDERS[entity.python_expand]
        wanted = None
        if query.limit and not (include_total or query.functions):
            order = _document_order(entity, query)
            if order is not None:
                cursor = cursor.sort(*order).allow_disk_use(True)
            if order is not None or not query.order_by:
                wanted = (query.offset or 0) + query.limit
        rows = []
        batch = []
        async for document in cursor:
            batch.append(document)
            if len(batch) < PYTHON_BATCH_SIZE:
                continue
            rows.extend(
                await asyncio.to_thread(
                    _expand_batch, expander, batch, match, deadline
                )
            )
            batch = []
            if wanted is not None and len(rows) >= wanted:
                break
        if batch:
            rows.extend(
                await asyncio.to_thread(
                    _expand_batch, expander, batch, match, deadline
                )
            )
        return rows

    async def _fact_path_candidates(self, entity, match: dict):
        if not entity.path_source or not match:
            return None
        path_match = _path_node(match, PATH_COLUMNS)
        if path_match is None:
            return None
        options = {}
        timeout = _query_timeout.get()
        if timeout:
            options["maxTimeMS"] = int(timeout * 1000)
        values = await self.collection(entity.collection).distinct(
            entity.path_source, **options
        )
        names = set()
        entries = []
        for entry in values:
            if not isinstance(entry, str):
                continue
            path, _value_type = decode_fact_path(entry)
            if matcher.matches({"name": path[0], "path": path}, path_match):
                names.add(path[0])
                entries.append(entry)
        return names, sorted(entries)


PYTHON_BATCH_SIZE = 200
DEEP_OFFSET = 10000
INDEX_KEYS_TTL = 300
STREAM_BATCH_SIZE = 1000


class RowStream:
    def __init__(self, cursor, first: list):
        self._cursor = cursor
        self._first = first
        self.scalar = None

    @classmethod
    def empty(cls):
        return cls(None, [])

    async def batches(self):
        batch = self._first
        while batch:
            yield self._shape(batch)
            if self._cursor is None or len(batch) < STREAM_BATCH_SIZE:
                return
            batch = await self._cursor.to_list(length=STREAM_BATCH_SIZE)

    def _shape(self, batch: list) -> list:
        if self.scalar:
            return [row.get(self.scalar) for row in batch]
        return batch

    async def close(self) -> None:
        if self._cursor is not None:
            await self._cursor.close()


def _within_cap(rows: list, cap: Optional[int]) -> list:
    if cap is not None and len(rows) > cap:
        raise page_too_large(cap)
    return rows


MAX_PATH_PREFILTER = 100
PATH_COLUMNS = ("name", "path")


def _path_node(node, columns: tuple):
    if not isinstance(node, dict) or not node:
        return None
    parts = []
    for key, value in node.items():
        if key == "$and":
            for child in value:
                derived = _path_node(child, columns)
                if derived is not None:
                    parts.append(derived)
        elif key == "$or":
            branches = []
            for child in value:
                derived = _path_node(child, columns)
                if derived is None:
                    branches = []
                    break
                branches.append(derived)
            if branches:
                parts.append({"$or": branches})
        elif key in columns:
            parts.append({key: value})
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


def _top_conjuncts(match: dict) -> list:
    clauses = []
    for key, value in match.items():
        if key == "$and":
            for child in value:
                clauses.extend(_top_conjuncts(child))
        else:
            clauses.append({key: value})
    return clauses


def _covering_prefilter(entity, prefilter: dict):
    spec = entity.covering_index
    if not spec:
        return None
    fields = set()
    _collect_filter_fields(prefilter, fields)
    if spec["prefix"] in fields or not fields <= set(spec["fields"]):
        return None
    return _and_filters(prefilter, {spec["prefix"]: {"$in": list(spec["values"])}})


def _collect_filter_fields(node, fields: set) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in ("$and", "$or", "$nor") and isinstance(value, list):
            for child in value:
                _collect_filter_fields(child, fields)
        else:
            fields.add(key)


def _and_filters(left: dict, right: dict) -> dict:
    if not left:
        return right
    return {"$and": [left, right]}


def _document_order(entity, query: Query):
    if not query.order_by:
        return None
    column_name, direction = query.order_by[0]
    column = entity.by_name.get(column_name)
    if column is None or column.prefilter != "id" or column.prefilter_kind != "path":
        return None
    return column.prefilter, pymongo.ASCENDING if direction > 0 else pymongo.DESCENDING


def _expand_batch(expander, documents: list, match: dict, deadline) -> list:
    rows = []
    for document in documents:
        if deadline is not None and time.monotonic() > deadline:
            raise PuppetDBQueryError("query exceeded its timeout", status_code=500)
        for row in expander(document):
            if match and not matcher.matches(row, match):
                continue
            rows.append(row)
    return rows


def _python_projection(entity, keys) -> dict:
    projection = dict(PYTHON_PROJECTIONS[entity.python_expand])
    if not keys or len(keys) > MAX_PINNED_KEYS:
        return projection
    if any(not SAFE_KEY.match(key) for key in keys):
        return projection
    projection.pop("facts")
    for key in sorted(keys):
        projection[f"facts.{key}"] = 1
    return projection


def _null_fill_stages(names: set) -> list:
    if not names:
        return []
    return [{"$set": {name: {"$ifNull": [f"${name}", None]} for name in sorted(names)}}]


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


def build_early_sort(entity, query: Query, document_rows_only: bool = True):
    if not query.order_by or query.functions:
        return None
    if document_rows_only and not entity.document_rows:
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


DISTINCT_EVENT_KEYS = ("node_id", "resource_type", "resource_title", "property", "name")
PARTITION_PATHS = ("node_id", "latest")


def _distinct_event_stages(start, end) -> list:
    return [
        {"$match": {"timestamp": {"$gte": start, "$lte": end}}},
        {
            "$group": {
                "_id": {key: f"${key}" for key in DISTINCT_EVENT_KEYS},
                "latest": {"$max": "$timestamp"},
                "events": {"$push": "$$ROOT"},
            }
        },
        {
            "$project": {
                "events": {
                    "$filter": {
                        "input": "$events",
                        "as": "event",
                        "cond": {"$eq": ["$$event.timestamp", "$latest"]},
                    }
                }
            }
        },
        {"$unwind": "$events"},
        {"$replaceRoot": {"newRoot": "$events"}},
    ]


def _partition_prefilter(prefilter: dict) -> dict:
    clauses = prefilter.get("$and") if set(prefilter) == {"$and"} else [prefilter]
    kept = [
        clause
        for clause in clauses
        if isinstance(clause, dict) and set(clause) and set(clause) <= set(PARTITION_PATHS)
    ]
    if not kept:
        return {}
    return kept[0] if len(kept) == 1 else {"$and": kept}


def _rewrite_to_storage(entity, stages: list):
    paths = {}
    for column in entity.columns:
        path = _storage_path(entity, column.name)
        if path is not None:
            paths[column.name] = path
    names = {column.name for column in entity.columns}

    def rewrite(node):
        if isinstance(node, dict):
            return {key: rewrite(value) for key, value in node.items()}
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if isinstance(node, str) and node.startswith("$") and not node.startswith("$$"):
            head, _sep, rest = node[1:].partition(".")
            if head in paths:
                return "$" + paths[head] + (f".{rest}" if rest else "")
            if head in names:
                raise _NotRewritable()
        return node

    try:
        return rewrite(stages)
    except _NotRewritable:
        return None


class _NotRewritable(Exception):
    pass


def _document_level(entity, match: dict) -> bool:
    if not match:
        return True
    spec = entity.element_filter or {}
    prefixes = [
        prefix
        for prefix in (spec.get("prefix"), spec.get("field") and f"{spec['field']}.")
        if prefix
    ]
    names = set()
    _collect_match_columns(match, names)
    for name in names:
        head = name.split(".", 1)[0]
        path = _storage_path(entity, head)
        if path is None:
            path = _document_prefilter_path(entity, head)
        if path is None or any(path.startswith(prefix) for prefix in prefixes):
            return False
    return True


def _document_prefilter_path(entity, column_name: str) -> Optional[str]:
    column = entity.by_name.get(column_name)
    if column is None or column.virtual or column.prefilter_kind != "node_state":
        return None
    return column.prefilter


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
        elif key == TUPLE_IN:
            into.update(value["keys"])
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
        elif key in ("$nor", "__never__", TUPLE_IN):
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
        elif key in ("$nor", "__never__", TUPLE_IN):
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
    return _element_node(entity, spec, match)


def _element_node(entity, spec, node):
    if not isinstance(node, dict) or not node:
        return None
    parts = []
    for key, value in node.items():
        if key == "$and":
            for child in value:
                derived = _element_node(entity, spec, child)
                if derived is not None:
                    parts.append(derived)
        elif key == "$or":
            branches = []
            for child in value:
                derived = _element_node(entity, spec, child)
                if derived is None:
                    branches = []
                    break
                branches.append(derived)
            if branches:
                parts.append(
                    branches[0] if len(branches) == 1 else {"$or": branches}
                )
        elif key in ("$nor", "__never__", TUPLE_IN):
            continue
        else:
            leaf = _element_leaf(entity, spec, key, value)
            if leaf is not None:
                parts.append(leaf)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


def _element_leaf(entity, spec, key: str, condition):
    column = entity.by_name.get(key)
    rest = ""
    if column is None and "." in key:
        head, tail = key.split(".", 1)
        column = entity.by_name.get(head)
        rest = "." + tail
    if column is None:
        return None
    element = entity.element_path(column.name)
    if element is None:
        return None

    field = f"$$item.{element}{rest}"
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


def _mongo_safe(match: dict, tuple_fields: dict):
    if isinstance(match, dict):
        cleaned = {}
        for key, value in match.items():
            if key == "__never__":
                cleaned.update(NEVER_MATCH)
            elif key == TUPLE_IN:
                cleaned.update(_tuple_condition(value, tuple_fields))
            elif key in ("$and", "$or", "$nor"):
                cleaned[key] = [_mongo_safe(item, tuple_fields) for item in value]
            else:
                cleaned[key] = value
        return cleaned
    return match


def _tuple_condition(spec: dict, tuple_fields: dict) -> dict:
    name = f"{TUPLE_FIELD_PREFIX}{len(tuple_fields)}"
    tuple_fields[name] = {
        str(index): {"$ifNull": [f"${key}", None]}
        for index, key in enumerate(spec["keys"])
    }
    values = [
        {str(index): item for index, item in enumerate(row)}
        for row in spec["values"]
    ]
    return {name: {"$in": values}}


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


def _skip_behind_match(tail: list, offset: int) -> list:
    stages = list(tail)
    at = next(index for index, stage in enumerate(stages) if "$match" in stage)
    stages.insert(at + 1, {"$skip": offset})
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
        for path, leaf in walk_fact(value, [name]):
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


def expand_fact_paths(entries: list) -> list:
    rows = []
    for entry in entries:
        if not isinstance(entry, str):
            continue
        path, value_type = decode_fact_path(entry)
        rows.append({"name": path[0], "path": path, "type": value_type})
    return rows


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
}
