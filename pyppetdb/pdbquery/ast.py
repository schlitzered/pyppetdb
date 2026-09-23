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
from typing import Any
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.errors import bad_arity
from pyppetdb.pdbquery.errors import bad_operand
from pyppetdb.pdbquery.errors import bad_timestamp
from pyppetdb.pdbquery.errors import comparison_not_allowed
from pyppetdb.pdbquery.errors import incompatible_numeric
from pyppetdb.pdbquery.errors import incompatible_types
from pyppetdb.pdbquery.errors import bad_operator_arity
from pyppetdb.pdbquery.errors import bad_regex
from pyppetdb.pdbquery.errors import unknown_field
from pyppetdb.pdbquery.errors import unknown_operator

BINARY_OPS = ("=", "~", "~>", ">", "<", ">=", "<=")
COMPARISON_OPS = {">": "$gt", "<": "$lt", ">=": "$gte", "<=": "$lte"}
STRUCTURED_TYPES = ("json", "path", "array")
BOOLEAN_OPS = ("and", "or", "not")
AGGREGATE_FUNCTIONS = ("count", "avg", "sum", "min", "max", "to_string")
TUPLE_IN = "__tuple_in__"
SELECT_PREFIX = "select_"
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


class Function(BaseModel):
    name: str
    column: Optional[str] = None
    alias: Optional[str] = None


class Query(BaseModel):
    entity: str
    filter: Optional[List[Any]] = None
    columns: Optional[List[str]] = None
    functions: List[Function] = Field(default_factory=list)
    group_by: Optional[List[str]] = None
    order_by: Optional[List[Any]] = None
    limit: Optional[int] = None
    offset: Optional[int] = None


def parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def looks_like_timestamp(value) -> bool:
    return isinstance(value, str) and bool(TIMESTAMP_RE.match(value.strip()))


def check_depth(ast, max_depth: int, max_subquery_depth: int) -> None:
    if not max_depth and not max_subquery_depth:
        return
    try:
        _check_depth(
            ast,
            max_depth or None,
            max_subquery_depth or None,
            max_depth,
            max_subquery_depth,
        )
    except RecursionError:
        raise PuppetDBQueryError("query is nested too deeply")


def _check_depth(node, depth_left, subqueries_left, max_depth, max_subqueries, root=True) -> None:
    if not isinstance(node, list) or not node:
        return
    if depth_left is not None:
        if depth_left <= 0:
            raise PuppetDBQueryError(
                f"query is nested more than {max_depth} levels deep"
            )
        depth_left -= 1
    operator = node[0] if isinstance(node[0], str) else ""
    if (
        operator.startswith(SELECT_PREFIX)
        or operator == "subquery"
        or (operator == "from" and not root)
    ):
        if subqueries_left is not None:
            subqueries_left -= 1
            if subqueries_left < 0:
                raise PuppetDBQueryError(
                    f"query nests more than {max_subqueries} "
                    f"levels of subqueries"
                )
    for item in node:
        _check_depth(
            item, depth_left, subqueries_left, max_depth, max_subqueries, False
        )


def parse_query(entity: str, ast, entities) -> Query:
    if ast is None:
        return Query(entity=entity)
    if not isinstance(ast, list):
        raise PuppetDBQueryError(f"{ast!r} is not a valid query term")
    if not ast:
        return Query(entity=entity)

    operator = ast[0]
    if operator == "from":
        if len(ast) < 2 or not isinstance(ast[1], str):
            raise bad_arity("from", "an entity name")
        rest = list(ast[2:])
        inner = None
        if rest and not is_paging_clause(rest[0]):
            inner = rest.pop(0)
        query = parse_query(ast[1], inner, entities)
        _apply_paging_clauses(query, rest)
        return query
    if operator == "extract":
        return _parse_extract(entity, ast, entities)
    return Query(entity=entity, filter=ast)


def is_paging_clause(node) -> bool:
    return (
        isinstance(node, list)
        and bool(node)
        and node[0] in ("limit", "offset", "order_by", "group_by")
    )


def _apply_paging_clauses(query: Query, clauses) -> None:
    for clause in clauses:
        if not isinstance(clause, list) or not clause:
            raise unknown_operator(clause)
        name = clause[0]
        if name == "limit":
            query.limit = _positive_int("limit", clause[1:])
        elif name == "offset":
            query.offset = _positive_int("offset", clause[1:], allow_zero=True)
        elif name == "order_by":
            query.order_by = _parse_order_by(clause[1:])
        elif name == "group_by":
            query.group_by = list(clause[1:])
        else:
            raise unknown_operator(name)


def _positive_int(name: str, args, allow_zero: bool = False) -> int:
    if len(args) != 1 or not isinstance(args[0], int) or isinstance(args[0], bool):
        raise bad_arity(name, "exactly one integer argument")
    value = args[0]
    if value < 0 or (value == 0 and not allow_zero):
        raise PuppetDBQueryError(
            f"Illegal value '{value}' for :{name}; expected a positive non-zero integer"
        )
    return value


def _parse_order_by(args) -> list:
    order = []
    for entry in args:
        if isinstance(entry, str):
            order.append((entry, 1))
            continue
        if isinstance(entry, list) and entry:
            for item in entry:
                if isinstance(item, str):
                    order.append((item, 1))
                elif (
                    isinstance(item, list)
                    and len(item) == 2
                    and isinstance(item[0], str)
                ):
                    direction = str(item[1]).lower()
                    if direction not in ("asc", "desc"):
                        raise PuppetDBQueryError(
                            f"Illegal value '{item[1]}' for :order_by; "
                            "expected 'asc' or 'desc'"
                        )
                    order.append((item[0], 1 if direction == "asc" else -1))
                else:
                    raise unknown_operator(item)
            continue
        raise unknown_operator(entry)
    return order


def _parse_extract(entity: str, ast, entities) -> Query:
    if len(ast) < 2:
        raise bad_arity("extract", "at least one column")
    columns, functions = _parse_extract_columns(ast[1])
    inner = None
    clauses = []
    for item in ast[2:]:
        if isinstance(item, list) and item and item[0] == "group_by":
            clauses.append(item)
        elif isinstance(item, list) and item and item[0] in ("limit", "offset", "order_by"):
            clauses.append(item)
        elif inner is None:
            inner = item
        else:
            raise unknown_operator(item)
    query = Query(
        entity=entity,
        filter=inner,
        columns=columns,
        functions=functions,
    )
    _apply_paging_clauses(query, clauses)
    return query


def _parse_extract_columns(spec):
    if isinstance(spec, str):
        return [spec], []
    if not isinstance(spec, list):
        raise PuppetDBQueryError(f"{spec!r} is not a valid extract column list")
    columns = []
    functions = []
    for item in spec:
        if isinstance(item, str):
            columns.append(item)
            continue
        if isinstance(item, list) and item and item[0] == "function":
            if len(item) < 2 or not isinstance(item[1], str):
                raise bad_arity("function", "a function name")
            name = item[1]
            if name not in AGGREGATE_FUNCTIONS:
                raise PuppetDBQueryError(
                    f"Unsupported aggregate function '{name}'. "
                    f"Supported functions are [{', '.join(AGGREGATE_FUNCTIONS)}]."
                )
            column = item[2] if len(item) > 2 else None
            if column is not None and not isinstance(column, str):
                raise PuppetDBQueryError(
                    f"{column!r} is not a valid argument for function '{name}'"
                )
            if len(item) > 3 and name != "to_string":
                raise bad_arity(f"function {name}", "at most one column argument")
            alias = name if column is None else f"{name}"
            functions.append(Function(name=name, column=column, alias=alias))
            continue
        raise PuppetDBQueryError(f"{item!r} is not a valid extract column")
    return columns, functions


class FilterCompiler:
    def __init__(self, entity, engine=None, validate_only: bool = False):
        self._entity = entity
        self._engine = engine
        self._validate_only = validate_only

    @property
    def entity(self):
        return self._entity

    async def compile(self, node) -> dict:
        if node is None:
            return {}
        if not isinstance(node, list) or not node:
            raise unknown_operator(node)
        operator = node[0]
        if operator in BOOLEAN_OPS:
            return await self._compile_boolean(node)
        if operator in BINARY_OPS:
            return await self._compile_binary(node)
        if operator == "null?":
            return await self._compile_null(node)
        if operator == "in":
            return await self._compile_in(node)
        if operator == "subquery":
            return await self._compile_subquery(node)
        raise unknown_operator(operator)

    async def _compile_boolean(self, node) -> dict:
        operator = node[0]
        if operator == "not":
            if len(node) != 2:
                raise bad_operator_arity("not", len(node) - 1)
            inner = await self.compile(node[1])
            if not inner:
                return {"__never__": True}
            return {"$nor": [inner]}
        if len(node) == 1:
            raise bad_operator_arity(operator, 0)
        parts = []
        for child in node[1:]:
            compiled = await self.compile(child)
            if compiled:
                parts.append(compiled)
        if not parts:
            return {}
        if len(parts) == 1:
            return parts[0]
        return {"$and" if operator == "and" else "$or": parts}

    async def _compile_binary(self, node) -> dict:
        operator = node[0]
        if len(node) != 3:
            raise bad_arity(operator, "exactly two arguments")
        column, path = self._resolve_field(node[1])
        if column.virtual:
            return await self._compile_virtual(column, node)
        label = _field_label(node[1])
        if operator == "~":
            if column.type not in ("string", "json"):
                raise PuppetDBQueryError(
                    f"Argument \"{node[1]}\" to ~ must be a string"
                )
            return {path: {"$regex": _regex_operand(label, "~", node[2])}}
        if operator == "~>":
            if column.type != "path" or not self._entity.python_expand:
                raise PuppetDBQueryError(
                    f"Query operator ~> is not allowed on field {label}"
                )
            operator_key = (
                "__regex_array_full__"
                if self._entity.name == "fact-paths"
                else "__regex_array__"
            )
            return {path: {operator_key: _regex_array_operand(label, node[2])}}
        operand = _check_operand(column, label, operator, node[2])
        _check_operand_type(column, label, operator, operand)
        value = self._coerce(column, operand, operator)
        if operator == "=":
            return {path: value}
        return {path: {COMPARISON_OPS[operator]: value}}

    async def _compile_null(self, node) -> dict:
        if len(node) != 3 or not isinstance(node[2], bool):
            raise bad_arity("null?", "a field and a boolean")
        column, path = self._resolve_field(node[1])
        if column.virtual:
            return await self._compile_virtual(column, node)
        if node[2]:
            return {path: None}
        return {path: {"$ne": None}}

    async def _compile_virtual(self, column, node) -> dict:
        spec = column.virtual
        select = "select_" + spec["entity"].replace("-", "_")
        inner = [node[0], spec["column"]] + list(node[2:])
        return await self._compile_in(
            ["in", spec["local"], ["extract", spec["remote"], [select, inner]]]
        )

    async def _compile_in(self, node) -> dict:
        if len(node) != 3:
            raise bad_arity("in", "exactly two arguments")
        fields = node[1] if isinstance(node[1], list) else [node[1]]
        if isinstance(node[1], list) and node[1] and node[1][0] in ("parameter", "fact"):
            fields = [node[1]]
        resolved = [self._resolve_field(item) for item in fields]
        value = node[2]

        if isinstance(value, list) and value and value[0] == "array":
            if len(resolved) != 1:
                raise PuppetDBQueryError(
                    "an array literal can only be matched against a single field"
                )
            if len(value) != 2 or not isinstance(value[1], list):
                raise bad_arity("array", "exactly one list argument")
            column, path = resolved[0]
            label = _field_label(fields[0])
            values = [
                self._coerce(column, _check_operand(column, label, "=", item), "=")
                for item in value[1]
            ]
            return {path: {"$in": values}}

        rows = await self._run_subquery(value, len(resolved))
        if self._validate_only:
            return {}
        if not rows:
            return {"__never__": True}
        if len(resolved) == 1:
            column, path = resolved[0]
            return {path: {"$in": [row[0] for row in rows]}}
        paths = [path for _column, path in resolved]
        clauses = [
            {path: {"$in": _unique(row[index] for row in rows)}}
            for index, path in enumerate(paths)
        ]
        clauses.append(
            {TUPLE_IN: {"keys": paths, "values": [list(row) for row in rows]}}
        )
        return {"$and": clauses}

    async def _run_subquery(self, node, arity: int):
        entity_name, column_spec, inner_ast = _subquery_parts(node)
        columns, _functions = _parse_extract_columns(column_spec)
        if len(columns) != arity:
            raise PuppetDBQueryError(
                f"subquery must extract {arity} column(s), got {len(columns)}"
            )
        if self._validate_only:
            await self._engine.validate(
                entity_name, ["extract", column_spec, inner_ast]
            )
            return []
        return await self._engine.select(entity_name, columns, inner_ast)

    async def _compile_subquery(self, node) -> dict:
        if len(node) not in (2, 3) or not isinstance(node[1], str):
            raise bad_arity("subquery", "an entity name and an optional query")
        entity_name = self._engine.entity(node[1]).name
        inner_ast = node[2] if len(node) == 3 else None
        join = self._entity.relations.get(entity_name)
        if join is None:
            raise PuppetDBQueryError(
                f"No implicit relationship between {self._entity.name} and {entity_name}"
            )
        local, remote = join
        if self._validate_only:
            await self._engine.validate(
                entity_name, ["extract", [remote], inner_ast]
            )
            return {}
        rows = await self._engine.select(entity_name, [remote], inner_ast)
        if not rows:
            return {"__never__": True}
        column, path = self._resolve_field(local)
        return {path: {"$in": [row[0] for row in rows]}}

    def _resolve_field(self, field):
        column, path = self._entity.resolve(field)
        if column is None:
            raise unknown_field(
                _field_label(field),
                self._entity.name,
                self._entity.queryable_names(),
            )
        return column, path

    @staticmethod
    def _coerce(column, value: Any, operator: str):
        if column.type == "state" and isinstance(value, bool):
            return "active" if value else "inactive"
        if column.type == "timestamp" and looks_like_timestamp(value):
            return parse_timestamp(value)
        if column.type == "integer" and isinstance(value, str) and operator != "~":
            try:
                return int(value)
            except ValueError:
                return value
        return value


COMPARABLE_TYPES = ("integer", "timestamp", "json")
FACT_VALUE_COLUMNS = ("value", "facts")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_operand_type(column, label: str, operator: str, value) -> None:
    if column.type == "timestamp" and isinstance(value, str):
        if not looks_like_timestamp(value):
            raise bad_timestamp(value)
    if operator in COMPARISON_OPS:
        if column.type not in COMPARABLE_TYPES:
            raise comparison_not_allowed(label)
        if column.type == "integer" and not _is_number(value):
            raise incompatible_types(value, operator)
        if column.type == "json" and column.name in FACT_VALUE_COLUMNS and not _is_number(value):
            raise incompatible_types(value, operator)
        return
    if operator == "=" and column.type == "integer" and isinstance(value, str):
        raise incompatible_numeric(value, label)


def _check_operand(column, label: str, operator: str, value):
    if not isinstance(value, (dict, list)):
        return value
    if operator == "=" and column.type in STRUCTURED_TYPES:
        _reject_query_operators(label, operator, value)
        return value
    raise bad_operand(operator, label, value, "a scalar value")


def _reject_query_operators(label: str, operator: str, value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("$"):
                raise bad_operand(operator, label, value, "a literal value")
            _reject_query_operators(label, operator, item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_query_operators(label, operator, item)


def _regex_operand(label: str, operator: str, value) -> str:
    if not isinstance(value, str):
        raise bad_operand(operator, label, value, "a string")
    try:
        re.compile(value)
    except re.error as err:
        raise bad_regex(label, value, str(err)) from err
    return value


def _regex_array_operand(label: str, value) -> list:
    if not isinstance(value, list):
        raise bad_operand("~>", label, value, "an array of strings")
    patterns = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise PuppetDBQueryError(
                f"Regex array element wasn't string or integer in {value!r}"
            )
        _regex_operand(label, "~>", str(item))
        patterns.append(item)
    return patterns


def _unique(values) -> list:
    seen = set()
    unique = []
    for value in values:
        try:
            if value in seen:
                continue
            seen.add(value)
        except TypeError:
            pass
        unique.append(value)
    return unique


def _subquery_parts(node):
    if not isinstance(node, list) or not node:
        raise PuppetDBQueryError(f"{node!r} is not a valid subquery")
    if node[0] == "extract":
        if len(node) < 3:
            raise bad_arity("extract", "columns and a subquery")
        target = node[2]
        if (
            isinstance(target, list)
            and target
            and isinstance(target[0], str)
            and target[0].startswith(SELECT_PREFIX)
        ):
            entity_name = target[0][len(SELECT_PREFIX):]
            return entity_name, node[1], target[1] if len(target) > 1 else None
        if isinstance(target, list) and target and target[0] == "from":
            if len(target) < 2 or not isinstance(target[1], str):
                raise bad_arity("from", "an entity name")
            return target[1], node[1], target[2] if len(target) > 2 else None
        raise PuppetDBQueryError(f"{target!r} is not a valid subquery target")
    if node[0] == "from":
        if len(node) < 3 or not isinstance(node[1], str):
            raise bad_arity("from", "an entity name and an extract expression")
        inner = node[2]
        if not isinstance(inner, list) or not inner or inner[0] != "extract":
            raise PuppetDBQueryError(
                f"{inner!r} is not a valid subquery; expected an extract expression"
            )
        return node[1], inner[1], inner[2] if len(inner) > 2 else None
    raise PuppetDBQueryError(
        f"{node!r} is not a valid subquery; expected an extract expression"
    )


def _field_label(field) -> str:
    if isinstance(field, str):
        return field
    if isinstance(field, list) and field and isinstance(field[0], str):
        return " ".join(str(item) for item in field)
    return repr(field)
