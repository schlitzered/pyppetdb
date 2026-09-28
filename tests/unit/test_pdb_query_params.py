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

from pyppetdb.pdb.query import params
from pyppetdb.pdb.query.errors import PuppetDBQueryError


class TestValidateParams(unittest.TestCase):
    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            params.validate_params({"query": None, "bogus": "1"}, "typical")
        self.assertEqual(str(ctx.exception.message), "Unsupported query parameter 'bogus'")

    def test_required_parameter_is_enforced(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            params.validate_params({}, "root")
        self.assertEqual(str(ctx.exception.message), "Missing required query parameter 'query'")

    def test_status_routes_take_no_paging(self):
        with self.assertRaises(PuppetDBQueryError):
            params.validate_params({"limit": "1"}, "status")
        params.validate_params({"pretty": "true", "timeout": "1"}, "status")

    def test_distinct_only_on_event_routes(self):
        params.validate_params({"distinct_resources": "true"}, "events")
        with self.assertRaises(PuppetDBQueryError):
            params.validate_params({"distinct_resources": "true"}, "typical")

    def test_aggregate_event_counts_take_no_paging(self):
        with self.assertRaises(PuppetDBQueryError):
            params.validate_params({"summarize_by": "certname", "limit": "1"}, "aggregate-event-counts")
        params.validate_params({"summarize_by": "certname", "query": None}, "aggregate-event-counts")


class TestScalarParams(unittest.TestCase):
    def test_timeout_accepts_integers_and_floats(self):
        self.assertEqual(params.parse_timeout("5"), 5)
        self.assertEqual(params.parse_timeout("2.5"), 2.5)
        self.assertEqual(params.parse_timeout(".5"), 0.5)
        self.assertEqual(params.parse_timeout("0"), 0)
        self.assertIsNone(params.parse_timeout(None))
        for bad in ("-1", "abc", "1e3", True):
            with self.assertRaises(PuppetDBQueryError, msg=bad):
                params.parse_timeout(bad)

    def test_explain_only_accepts_analyze(self):
        self.assertEqual(params.parse_explain("analyze"), "analyze")
        self.assertIsNone(params.parse_explain(None))
        with self.assertRaises(PuppetDBQueryError):
            params.parse_explain("true")

    def test_bool_parsing(self):
        self.assertTrue(params.parse_bool("true"))
        self.assertTrue(params.parse_bool(True))
        self.assertFalse(params.parse_bool("yes"))
        self.assertFalse(params.parse_bool(None))


class TestDistinct(unittest.TestCase):
    def test_all_three_parameters_give_a_window(self):
        window = params.parse_distinct(
            {
                "distinct_resources": "true",
                "distinct_start_time": "2026-01-01T00:00:00Z",
                "distinct_end_time": "2026-01-02T00:00:00Z",
            }
        )
        self.assertEqual(window[0].year, 2026)
        self.assertIsInstance(window[1], datetime)

    def test_false_flag_disables_the_window(self):
        self.assertIsNone(
            params.parse_distinct(
                {
                    "distinct_resources": "false",
                    "distinct_start_time": "2026-01-01T00:00:00Z",
                    "distinct_end_time": "2026-01-02T00:00:00Z",
                }
            )
        )

    def test_partial_parameters_are_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            params.parse_distinct({"distinct_resources": "true"})
        self.assertIn("requires accompanying parameters", ctx.exception.message)
        with self.assertRaises(PuppetDBQueryError) as ctx:
            params.parse_distinct(
                {"distinct_start_time": "2026-01-01T00:00:00Z", "distinct_end_time": "x"}
            )
        self.assertIn("must accompany", ctx.exception.message)
        with self.assertRaises(PuppetDBQueryError) as ctx:
            params.parse_distinct(
                {"distinct_resources": "true", "distinct_start_time": "nope", "distinct_end_time": "x"}
            )
        self.assertIn("must be valid datetime strings", ctx.exception.message)

    def test_nothing_given_means_no_window(self):
        self.assertIsNone(params.parse_distinct({"query": None}))


class TestActiveCriterion(unittest.TestCase):
    def test_detects_node_state_and_node_active_forms_anywhere(self):
        self.assertTrue(params.has_active_criterion(["=", "node_state", "inactive"]))
        self.assertTrue(params.has_active_criterion(["=", ["node", "active"], True]))
        self.assertTrue(
            params.has_active_criterion(
                ["and", ["=", "certname", "a"], ["not", ["=", "node_state", "active"]]]
            )
        )
        self.assertFalse(params.has_active_criterion(["=", "certname", "a"]))
        self.assertFalse(params.has_active_criterion(None))

    def test_root_entities_without_certname_are_not_restricted(self):
        self.assertFalse(params.root_entity_restricted("fact_paths"))
        self.assertFalse(params.root_entity_restricted("environments"))
        self.assertFalse(params.root_entity_restricted("packages"))
        self.assertTrue(params.root_entity_restricted("nodes"))
        self.assertTrue(params.root_entity_restricted("reports"))
