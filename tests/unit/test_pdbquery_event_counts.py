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

from pyppetdb.pdbquery import event_counts
from pyppetdb.pdbquery.errors import PuppetDBQueryError


class TestParams(unittest.TestCase):
    def test_summarize_by_required(self):
        with self.assertRaises(PuppetDBQueryError):
            event_counts.parse_summarize_by(None)

    def test_summarize_by_unknown(self):
        with self.assertRaises(PuppetDBQueryError):
            event_counts.parse_summarize_by("planet")

    def test_summarize_by_multiple(self):
        self.assertEqual(
            event_counts.parse_summarize_by("certname,resource"),
            ["certname", "resource"],
        )

    def test_count_by_default(self):
        self.assertEqual(event_counts.parse_count_by(None), "resource")

    def test_count_by_unknown(self):
        with self.assertRaises(PuppetDBQueryError):
            event_counts.parse_count_by("galaxy")

    def test_counts_filter_malformed(self):
        with self.assertRaises(PuppetDBQueryError):
            event_counts.parse_counts_filter("{nope")

    def test_counts_filter_valid(self):
        self.assertEqual(
            event_counts.parse_counts_filter('[">", "failures", 0]'),
            [">", "failures", 0],
        )

    def test_counts_filter_valid_nested(self):
        raw = (
            '["and", [">", "failures", 0], '
            '["not", ["or", ["=", "skips", 1], ["<=", "successes", 2]]]]'
        )
        self.assertEqual(
            event_counts.parse_counts_filter(raw),
            [
                "and",
                [">", "failures", 0],
                ["not", ["or", ["=", "skips", 1], ["<=", "successes", 2]]],
            ],
        )

    def test_counts_filter_rejects_bad_shapes(self):
        for raw in (
            '["not"]',
            '["not", ["=", "failures", 1], ["=", "skips", 1]]',
            '["and"]',
            '[">", "failures", "1"]',
            '["=", "failures", true]',
            '["=", "failures", 1.5]',
            '["=", "failures"]',
            '["=", "failures", 1, 2]',
            '["~", "failures", 1]',
            '["=", "bogus", 1]',
            '["and", ["=", "bogus", 1]]',
            '[["=", "failures", 1]]',
        ):
            with self.assertRaises(PuppetDBQueryError, msg=raw):
                event_counts.parse_counts_filter(raw)


class TestExtractColumnsQuery(unittest.TestCase):
    def test_wraps_a_filter(self):
        self.assertEqual(
            event_counts.extract_columns_query(["=", "certname", "a"]),
            [
                "extract",
                list(event_counts.SUMMARIZE_COLUMNS),
                ["=", "certname", "a"],
            ],
        )

    def test_wraps_an_absent_query(self):
        self.assertEqual(
            event_counts.extract_columns_query(None),
            ["extract", list(event_counts.SUMMARIZE_COLUMNS)],
        )

    def test_leaves_extract_and_from_alone(self):
        for ast in (
            ["extract", ["certname"], ["=", "status", "failure"]],
            ["from", "events"],
        ):
            self.assertEqual(event_counts.extract_columns_query(ast), ast)

    def test_stages_only_read_projected_columns(self):
        for summarize_by in event_counts.SUMMARIZE_BY:
            for count_by in event_counts.COUNT_BY:
                stages = event_counts.summary_stages(summarize_by, count_by)
                referenced = {
                    value.lstrip("$") for value in stages[0]["$group"]["_id"].values()
                }
                self.assertTrue(
                    referenced <= set(event_counts.SUMMARIZE_COLUMNS),
                    msg=(summarize_by, count_by, referenced),
                )


COUNTS = [
    {
        "subject_type": "certname",
        "subject": {"title": "a"},
        "failures": 1,
        "successes": 1,
        "noops": 0,
        "skips": 0,
    },
    {
        "subject_type": "certname",
        "subject": {"title": "b"},
        "failures": 0,
        "successes": 0,
        "noops": 0,
        "skips": 1,
    },
]


class TestSummaryStages(unittest.TestCase):
    def test_distinct_identities_are_counted_per_bucket_and_status(self):
        stages = event_counts.summary_stages("certname", "resource")
        self.assertEqual(
            stages[0]["$group"]["_id"],
            {
                "certname": "$certname",
                "status": "$status",
                "by_certname": "$certname",
                "by_resource_type": "$resource_type",
                "by_resource_title": "$resource_title",
            },
        )
        second = stages[1]["$group"]
        self.assertEqual(second["_id"], {"certname": "$_id.certname"})
        self.assertEqual(
            second["failures"],
            {"$sum": {"$cond": [{"$eq": ["$_id.status", "failure"]}, 1, 0]}},
        )
        self.assertEqual(
            set(second) - {"_id"}, {"failures", "successes", "noops", "skips"}
        )

    def test_count_by_certname_ignores_the_resource(self):
        stages = event_counts.summary_stages("certname", "certname")
        self.assertEqual(
            stages[0]["$group"]["_id"],
            {"certname": "$certname", "status": "$status", "by_certname": "$certname"},
        )

    def test_only_the_upstream_fields_are_emitted(self):
        project = event_counts.summary_stages("certname", "resource")[2]["$project"]
        self.assertEqual(
            set(project) - {"_id"},
            {"subject_type", "subject", "failures", "successes", "noops", "skips"},
        )
        self.assertEqual(project["subject_type"], {"$literal": "certname"})
        self.assertEqual(project["subject"], {"title": {"$ifNull": ["$_id.certname", None]}})

    def test_by_resource_subject_has_type_and_title(self):
        stages = event_counts.summary_stages("resource", "resource")
        self.assertEqual(
            stages[1]["$group"]["_id"],
            {"resource_type": "$_id.resource_type", "resource_title": "$_id.resource_title"},
        )
        self.assertEqual(
            stages[2]["$project"]["subject"],
            {
                "type": {"$ifNull": ["$_id.resource_type", None]},
                "title": {"$ifNull": ["$_id.resource_title", None]},
            },
        )

    def test_by_containing_class(self):
        stages = event_counts.summary_stages("containing_class", "resource")
        self.assertEqual(
            stages[2]["$project"]["subject"],
            {"title": {"$ifNull": ["$_id.containing_class", None]}},
        )


class TestSingleReportFastPath(unittest.TestCase):
    def test_detects_latest_report_and_report_hash_conjuncts(self):
        self.assertTrue(event_counts.single_report_per_node(["=", "latest_report?", True]))
        self.assertTrue(event_counts.single_report_per_node(["=", "report", "abc"]))
        self.assertTrue(
            event_counts.single_report_per_node(
                ["and", ["=", "status", "failure"], ["=", "latest_report?", True]]
            )
        )
        self.assertFalse(event_counts.single_report_per_node(["=", "latest_report?", False]))
        self.assertFalse(
            event_counts.single_report_per_node(["or", ["=", "latest_report?", True], ["=", "status", "noop"]])
        )
        self.assertFalse(event_counts.single_report_per_node(["=", "certname", "a"]))
        self.assertFalse(event_counts.single_report_per_node(None))

    def test_single_group_counts_first_events_only(self):
        stages = event_counts.summary_stages("containing_class", "resource", ["=", "latest_report?", True])
        self.assertEqual(len(stages), 3)
        first = stages[0]["$group"]
        self.assertEqual(
            first["_id"], {"containing_class": "$containing_class", "status": "$status"}
        )
        self.assertEqual(
            first["n"], {"$sum": {"$cond": [{"$eq": ["$first_for_resource", True]}, 1, 0]}}
        )
        second = stages[1]["$group"]
        self.assertEqual(second["_id"], {"containing_class": "$_id.containing_class"})
        self.assertEqual(
            second["failures"],
            {"$sum": {"$cond": [{"$eq": ["$_id.status", "failure"]}, "$n", 0]}},
        )

    def test_flag_follows_count_by(self):
        self.assertEqual(event_counts._first_flag("certname", "certname"), "first_for_certname")
        self.assertEqual(event_counts._first_flag("containing_class", "certname"), "first_for_class")
        self.assertEqual(event_counts._first_flag("resource", "certname"), "first_for_resource")
        self.assertEqual(event_counts._first_flag("containing_class", "resource"), "first_for_resource")

    def test_summary_projection_adds_the_flag_only_on_the_fast_path(self):
        self.assertEqual(event_counts.summary_projection("certname", "resource", None), {})
        self.assertEqual(
            event_counts.summary_projection("containing_class", "certname", ["=", "latest_report?", True]),
            {"first_for_class": "$first_for_class"},
        )


class TestCountsFilter(unittest.TestCase):
    def test_counts_filter(self):
        filtered = event_counts.apply_counts_filter(COUNTS, [">", "failures", 0])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["subject"]["title"], "a")

    def test_counts_filter_unknown_field(self):
        with self.assertRaises(PuppetDBQueryError):
            event_counts.apply_counts_filter(COUNTS, ["=", "bogus", 1])

    def test_counts_filter_bad_shape_is_a_query_error(self):
        for counts_filter in (
            ["not"],
            [">", "failures", "1"],
            ["nope", "failures", 1],
        ):
            with self.assertRaises(PuppetDBQueryError, msg=counts_filter):
                event_counts.apply_counts_filter(COUNTS, counts_filter)

    def test_counts_filter_nested(self):
        filtered = event_counts.apply_counts_filter(
            COUNTS,
            ["and", ["not", [">", "failures", 0]], ["=", "skips", 1]],
        )
        self.assertEqual([row["subject"]["title"] for row in filtered], ["b"])

    def test_counts_filter_on_a_field_summarize_never_emits(self):
        self.assertEqual(
            event_counts.apply_counts_filter(COUNTS, ["=", "corrective_noops", 0]),
            COUNTS,
        )
        self.assertEqual(
            event_counts.apply_counts_filter(COUNTS, [">", "corrective_noops", 0]),
            [],
        )

    def test_aggregate(self):
        totals = event_counts.aggregate(COUNTS)
        self.assertEqual(totals["total"], 2)
        self.assertEqual(totals["failures"], 1)
        self.assertEqual(totals["skips"], 1)


if __name__ == "__main__":
    unittest.main()
