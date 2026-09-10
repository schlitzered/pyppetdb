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

from pyppetdb.pdbquery import matcher


class TestNeverMatch(unittest.TestCase):
    def test_never_never_matches(self):
        self.assertFalse(matcher.matches({"a": 1}, {"__never__": True}))

    def test_never_inside_or_keeps_the_sibling_branch(self):
        query = {"$or": [{"__never__": True}, {"certname": "a"}]}
        self.assertTrue(matcher.matches({"certname": "a"}, query))
        self.assertFalse(matcher.matches({"certname": "b"}, query))

    def test_negated_never_matches_everything(self):
        self.assertTrue(
            matcher.matches({"certname": "a"}, {"$nor": [{"__never__": True}]})
        )


class TestRegex(unittest.TestCase):
    def test_non_string_values_do_not_match(self):
        self.assertFalse(matcher.matches({"value": False}, {"value": {"$regex": "^Red"}}))
        self.assertFalse(matcher.matches({"value": 42}, {"value": {"$regex": "^Red"}}))
        self.assertFalse(
            matcher.matches({"value": {"a": 1}}, {"value": {"$regex": "^Red"}})
        )
        self.assertTrue(
            matcher.matches({"value": "RedHat"}, {"value": {"$regex": "^Red"}})
        )


class TestRegexArray(unittest.TestCase):
    @staticmethod
    def match(path, patterns):
        return matcher.matches(
            {"path": path}, {"path": {"__regex_array__": patterns}}
        )

    def test_integer_pattern_only_matches_an_array_index(self):
        self.assertTrue(self.match(["tags", 0], ["tags", 0]))
        self.assertFalse(self.match(["tags", "0"], ["tags", 0]))

    def test_digit_only_pattern_never_matches_an_array_index(self):
        self.assertFalse(self.match(["tags", 0], ["tags", "0"]))
        self.assertTrue(self.match(["tags", "0"], ["tags", "0"]))

    def test_wildcard_patterns_match_mixed_elements(self):
        self.assertTrue(self.match(["tags", 0], ["ta.*", ".*"]))
        self.assertTrue(self.match(["tags", "0"], ["ta.*", ".*"]))

    def test_non_digit_pattern_matches_both_element_kinds(self):
        self.assertTrue(self.match(["tags", 0], ["tags", "[01]"]))
        self.assertTrue(self.match(["tags", "0"], ["tags", "[01]"]))

    def test_booleans_are_not_array_indexes(self):
        self.assertFalse(self.match(["tags", True], ["tags", 1]))

    def test_length_must_agree(self):
        self.assertFalse(self.match(["tags", 0], ["tags"]))
        self.assertFalse(self.match(["tags"], ["tags", "0"]))

    def test_non_matching_index(self):
        self.assertFalse(self.match(["tags", 0], ["tags", "1"]))

    def test_invalid_pattern_is_not_a_match_and_does_not_raise(self):
        self.assertFalse(self.match(["tags", 0], ["tags", "["]))

    def test_non_list_operands(self):
        self.assertFalse(self.match("tags", ["tags"]))
        self.assertFalse(self.match(["tags"], "tags"))


class TestEquals(unittest.TestCase):
    def test_integer_path_equality(self):
        self.assertTrue(
            matcher.matches({"path": ["tags", 0]}, {"path": ["tags", 0]})
        )
        self.assertFalse(
            matcher.matches({"path": ["tags", 0]}, {"path": ["tags", "0"]})
        )

    def test_missing_field_equals_none(self):
        self.assertTrue(matcher.matches({}, {"value": None}))
        self.assertFalse(matcher.matches({}, {"value": "x"}))
