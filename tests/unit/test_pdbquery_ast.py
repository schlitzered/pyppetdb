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

import unittest
from datetime import datetime

from pyppetdb.pdbquery.ast import FilterCompiler
from pyppetdb.pdbquery.ast import parse_query
from pyppetdb.pdbquery.entities import ENTITIES
from pyppetdb.pdbquery.entities import get_entity
from pyppetdb.pdbquery.errors import PuppetDBQueryError


class TestParseQuery(unittest.TestCase):
    def test_bare_filter(self):
        query = parse_query("nodes", ["=", "certname", "a"], ENTITIES)
        self.assertEqual(query.entity, "nodes")
        self.assertEqual(query.filter, ["=", "certname", "a"])

    def test_from_switches_entity(self):
        query = parse_query("nodes", ["from", "facts", ["=", "name", "os"]], ENTITIES)
        self.assertEqual(query.entity, "facts")
        self.assertEqual(query.filter, ["=", "name", "os"])

    def test_from_without_filter_but_with_clauses(self):
        query = parse_query("nodes", ["from", "nodes", ["order_by", ["certname"]]], ENTITIES)
        self.assertIsNone(query.filter)
        self.assertEqual(query.order_by, [("certname", 1)])

    def test_from_with_paging_clauses(self):
        query = parse_query(
            "nodes",
            [
                "from",
                "nodes",
                ["=", "certname", "a"],
                ["limit", 5],
                ["offset", 10],
                ["order_by", [["certname", "desc"]]],
            ],
            ENTITIES,
        )
        self.assertEqual(query.limit, 5)
        self.assertEqual(query.offset, 10)
        self.assertEqual(query.order_by, [("certname", -1)])

    def test_extract_columns_and_functions(self):
        query = parse_query(
            "nodes",
            ["extract", [["function", "count"], "certname"], ["group_by", "certname"]],
            ENTITIES,
        )
        self.assertEqual(query.columns, ["certname"])
        self.assertEqual(query.group_by, ["certname"])
        self.assertEqual(query.functions[0].name, "count")

    def test_extract_single_string_column(self):
        query = parse_query("nodes", ["extract", "certname"], ENTITIES)
        self.assertEqual(query.columns, ["certname"])

    def test_to_string_accepts_format_argument(self):
        query = parse_query(
            "reports",
            ["extract", [["function", "to_string", "producer_timestamp", "FMDAY"]]],
            ENTITIES,
        )
        self.assertEqual(query.functions[0].column, "producer_timestamp")

    def test_unknown_function_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_query("nodes", ["extract", [["function", "median"]]], ENTITIES)

    def test_zero_limit_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_query("nodes", ["from", "nodes", ["limit", 0]], ENTITIES)

    def test_zero_offset_allowed(self):
        query = parse_query("nodes", ["from", "nodes", ["offset", 0]], ENTITIES)
        self.assertEqual(query.offset, 0)

    def test_unknown_trailing_clause_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_query(
                "nodes",
                ["from", "nodes", ["=", "certname", "a"], ["nope", 1]],
                ENTITIES,
            )

    def test_bad_order_direction_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_query(
                "nodes", ["from", "nodes", ["order_by", [["certname", "sideways"]]]], ENTITIES
            )


class StubEngine:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    @staticmethod
    def entity(name):
        return get_entity(name)

    async def validate(self, entity_name, ast):
        self.calls.append(("validate", entity_name, ast))

    async def select(self, entity_name, columns, ast):
        self.calls.append(("select", entity_name, columns, ast))
        return self.rows


class TestFilterCompiler(unittest.IsolatedAsyncioTestCase):
    def compiler(self, entity="nodes", engine=None, validate_only=False):
        return FilterCompiler(
            get_entity(entity), engine=engine or StubEngine(), validate_only=validate_only
        )

    async def test_equality(self):
        result = await self.compiler().compile(["=", "certname", "a"])
        self.assertEqual(result, {"certname": "a"})

    async def test_and_or_not(self):
        compiler = self.compiler()
        self.assertEqual(
            await compiler.compile(["and", ["=", "certname", "a"], ["=", "certname", "b"]]),
            {"$and": [{"certname": "a"}, {"certname": "b"}]},
        )
        self.assertEqual(
            await compiler.compile(["or", ["=", "certname", "a"], ["=", "certname", "b"]]),
            {"$or": [{"certname": "a"}, {"certname": "b"}]},
        )
        self.assertEqual(
            await compiler.compile(["not", ["=", "certname", "a"]]),
            {"$nor": [{"certname": "a"}]},
        )

    async def test_empty_boolean_operators_are_rejected(self):
        compiler = self.compiler()
        for operator in ("and", "or"):
            with self.assertRaises(PuppetDBQueryError) as ctx:
                await compiler.compile([operator])
            self.assertEqual(
                str(ctx.exception),
                f"'{operator}' takes at least one argument, "
                f"but none were supplied",
            )

    async def test_not_arity_is_rejected(self):
        compiler = self.compiler()
        for node, supplied in ((["not"], 0), (["not", ["=", "certname", "a"], ["=", "certname", "b"]], 2)):
            with self.assertRaises(PuppetDBQueryError) as ctx:
                await compiler.compile(node)
            self.assertEqual(
                str(ctx.exception),
                f"'not' takes exactly one argument, but {supplied} were supplied",
            )

    async def test_empty_clause_inside_a_boolean_is_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            await self.compiler().compile(["and", ["=", "certname", "a"], []])

    async def test_not_does_not_drop_sibling_clauses(self):
        result = await self.compiler().compile(
            ["not", ["and", ["=", "certname", "a"], ["=", "latest_report_noop", True]]]
        )
        self.assertEqual(
            result,
            {"$nor": [{"$and": [{"certname": "a"}, {"latest_report_noop": True}]}]},
        )

    async def test_comparison_operators(self):
        compiler = self.compiler("resources")
        self.assertEqual(await compiler.compile([">", "line", 3]), {"line": {"$gt": 3}})
        self.assertEqual(await compiler.compile(["<=", "line", 3]), {"line": {"$lte": 3}})

    async def test_regex(self):
        result = await self.compiler().compile(["~", "certname", "^web"])
        self.assertEqual(result, {"certname": {"$regex": "^web"}})

    async def test_null(self):
        compiler = self.compiler()
        self.assertEqual(
            await compiler.compile(["null?", "latest_report_status", True]),
            {"latest_report_status": None},
        )
        self.assertEqual(
            await compiler.compile(["null?", "latest_report_status", False]),
            {"latest_report_status": {"$ne": None}},
        )

    async def test_timestamp_coercion(self):
        result = await self.compiler().compile(
            [">", "report_timestamp", "2026-03-24T09:30:23.308Z"]
        )
        self.assertIsInstance(result["report_timestamp"]["$gt"], datetime)

    async def test_node_state_field_form(self):
        result = await self.compiler().compile(["=", ["node", "active"], True])
        self.assertEqual(result, {"node_state": "active"})

    async def test_fact_field_form(self):
        result = await self.compiler().compile(["=", ["fact", "osfamily"], "Debian"])
        self.assertEqual(result, {"facts.osfamily": "Debian"})

    async def test_dotted_parameters(self):
        result = await self.compiler("resources").compile(
            ["=", "parameters.owner", "root"]
        )
        self.assertEqual(result, {"parameters.owner": "root"})

    async def test_parameter_field_form(self):
        result = await self.compiler("resources").compile(
            ["=", ["parameter", "owner"], "root"]
        )
        self.assertEqual(result, {"parameters.owner": "root"})

    async def test_in_with_array_literal(self):
        result = await self.compiler().compile(
            ["in", "certname", ["array", ["a", "b"]]]
        )
        self.assertEqual(result, {"certname": {"$in": ["a", "b"]}})

    async def test_in_with_subquery(self):
        engine = StubEngine(rows=[("a",), ("b",)])
        result = await self.compiler(engine=engine).compile(
            ["in", "certname", ["extract", "certname", ["select_facts", ["=", "name", "os"]]]]
        )
        self.assertEqual(result, {"certname": {"$in": ["a", "b"]}})
        self.assertEqual(engine.calls[0][:3], ("select", "facts", ["certname"]))

    async def test_in_with_from_subquery(self):
        engine = StubEngine(rows=[("a",)])
        result = await self.compiler(engine=engine).compile(
            ["in", "certname", ["from", "facts", ["extract", "certname", ["=", "name", "os"]]]]
        )
        self.assertEqual(result, {"certname": {"$in": ["a"]}})

    async def test_in_with_multiple_columns(self):
        engine = StubEngine(rows=[("a", "os"), ("b", "kernel")])
        result = await self.compiler("facts", engine=engine).compile(
            [
                "in",
                ["certname", "name"],
                ["extract", ["certname", "name"], ["select_fact_contents", None]],
            ]
        )
        self.assertEqual(
            result,
            {"$or": [{"certname": "a", "name": "os"}, {"certname": "b", "name": "kernel"}]},
        )

    async def test_empty_subquery_matches_nothing(self):
        engine = StubEngine(rows=[])
        result = await self.compiler(engine=engine).compile(
            ["in", "certname", ["extract", "certname", ["select_facts", None]]]
        )
        self.assertEqual(result, {"__never__": True})

    async def test_implicit_subquery(self):
        engine = StubEngine(rows=[("a",)])
        result = await self.compiler(engine=engine).compile(
            ["subquery", "facts", ["=", "name", "os"]]
        )
        self.assertEqual(result, {"certname": {"$in": ["a"]}})

    async def test_unknown_field_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile(["=", "sourcefile", "/foo"])
        self.assertIn("is not a queryable object for nodes", str(ctx.exception))

    async def test_unknown_operator_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            await self.compiler().compile(["nope", "certname", "a"])

    async def test_wrong_arity_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile(["=", "certname"])
        self.assertIn("requires exactly two arguments", str(ctx.exception))

    async def test_operator_document_rejected_for_equality(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile(["=", "certname", {"$ne": None}])
        self.assertIn("is not a valid value for field 'certname'", str(ctx.exception))

    async def test_array_operand_rejected_for_equality_on_scalar_field(self):
        with self.assertRaises(PuppetDBQueryError):
            await self.compiler().compile(["=", "certname", ["web01"]])

    async def test_operator_document_rejected_for_comparison(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile([">", "report_timestamp", {"$gt": ""}])
        self.assertIn("> requires a scalar value", str(ctx.exception))

    async def test_operator_document_rejected_inside_structured_operand(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler("fact-contents").compile(
                ["=", "value", {"$ne": None}]
            )
        self.assertIn("= requires a literal value", str(ctx.exception))

    async def test_operator_document_rejected_in_array_literal(self):
        with self.assertRaises(PuppetDBQueryError):
            await self.compiler().compile(
                ["in", "certname", ["array", [{"$ne": None}]]]
            )

    async def test_invalid_regex_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile(["~", "certname", "("])
        self.assertIn("Invalid regular expression", str(ctx.exception))

    async def test_non_string_regex_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler().compile(["~", "certname", 123])
        self.assertIn("~ requires a string", str(ctx.exception))

    async def test_regex_array_rejects_non_string_element(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler("fact-paths").compile(
                ["~>", "path", ["os", None]]
            )
        self.assertIn(
            "Regex array element wasn't string or integer", str(ctx.exception)
        )

    async def test_regex_array_rejects_invalid_element(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.compiler("fact-paths").compile(["~>", "path", ["os", "("]])
        self.assertIn("Invalid regular expression", str(ctx.exception))

    async def test_regex_array_rejects_non_array_operand(self):
        with self.assertRaises(PuppetDBQueryError):
            await self.compiler("fact-paths").compile(["~>", "path", "os"])

    async def test_regex_array_keeps_index_elements(self):
        result = await self.compiler("fact-paths").compile(
            ["~>", "path", ["my_structured_fact", "c", 1]]
        )
        self.assertEqual(
            result, {"path": {"__regex_array__": ["my_structured_fact", "c", 1]}}
        )

    async def test_regex_array_rejected_on_a_non_path_field(self):
        for entity, field in (("fact-paths", "name"), ("facts", "value")):
            with self.assertRaises(PuppetDBQueryError) as ctx:
                await self.compiler(entity).compile(["~>", field, ["os"]])
            self.assertIn(
                f"Query operator ~> is not allowed on field {field}",
                str(ctx.exception),
            )

    async def test_array_operand_allowed_for_path(self):
        result = await self.compiler("fact-paths").compile(
            ["=", "path", ["my_structured_fact", "c", 2]]
        )
        self.assertEqual(result, {"path": ["my_structured_fact", "c", 2]})

    async def test_array_operand_allowed_for_parameters(self):
        result = await self.compiler("resources").compile(
            ["=", ["parameter", "acl"], ["john:rwx", "fred:rwx"]]
        )
        self.assertEqual(result, {"parameters.acl": ["john:rwx", "fred:rwx"]})

    async def test_structured_operand_allowed_for_fact_value(self):
        result = await self.compiler("fact-contents").compile(
            ["=", "value", {"family": "Debian"}]
        )
        self.assertEqual(result, {"value": {"family": "Debian"}})

    async def test_validate_only_skips_subquery_execution(self):
        engine = StubEngine()
        compiler = self.compiler(engine=engine, validate_only=True)
        await compiler.compile(
            ["in", "certname", ["extract", "certname", ["select_facts", ["=", "name", "os"]]]]
        )
        self.assertEqual(engine.calls[0][0], "validate")


if __name__ == "__main__":
    unittest.main()
