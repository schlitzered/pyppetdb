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

ROWS = [
    {
        "certname": "a",
        "status": "success",
        "resource_type": "File",
        "resource_title": "/tmp/x",
        "containing_class": "Foo",
        "corrective_change": False,
    },
    {
        "certname": "a",
        "status": "failure",
        "resource_type": "File",
        "resource_title": "/tmp/y",
        "containing_class": "Foo",
        "corrective_change": True,
    },
    {
        "certname": "b",
        "status": "skipped",
        "resource_type": "Exec",
        "resource_title": "run",
        "containing_class": "Bar",
        "corrective_change": False,
    },
]


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

    def test_columns_cover_everything_summarize_reads(self):
        rows = [
            {field: row.get(field) for field in event_counts.SUMMARIZE_COLUMNS}
            for row in ROWS
        ]
        for summarize_by in event_counts.SUMMARIZE_BY:
            for count_by in event_counts.COUNT_BY:
                self.assertEqual(
                    event_counts.summarize(rows, summarize_by, count_by),
                    event_counts.summarize(ROWS, summarize_by, count_by),
                )


class TestSummarize(unittest.TestCase):
    def test_by_certname(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        by_subject = {row["subject"]["title"]: row for row in counts}
        self.assertEqual(by_subject["a"]["successes"], 1)
        self.assertEqual(by_subject["a"]["failures"], 1)
        self.assertEqual(by_subject["b"]["skips"], 1)

    def test_only_the_upstream_fields_are_emitted(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        row = next(item for item in counts if item["subject"]["title"] == "a")
        self.assertEqual(
            set(row), {"subject_type", "subject", "failures", "successes", "noops", "skips"}
        )

    def test_by_resource(self):
        counts = event_counts.summarize(ROWS, "resource", "resource")
        subjects = {(row["subject"]["type"], row["subject"]["title"]) for row in counts}
        self.assertIn(("File", "/tmp/x"), subjects)
        self.assertIn(("Exec", "run"), subjects)

    def test_count_by_certname_deduplicates(self):
        rows = ROWS + [dict(ROWS[0], resource_title="/tmp/z")]
        counts = event_counts.summarize(rows, "certname", "certname")
        row = next(item for item in counts if item["subject"]["title"] == "a")
        self.assertEqual(row["successes"], 1)

    def test_counts_filter(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        filtered = event_counts.apply_counts_filter(counts, [">", "failures", 0])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["subject"]["title"], "a")

    def test_counts_filter_unknown_field(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        with self.assertRaises(PuppetDBQueryError):
            event_counts.apply_counts_filter(counts, ["=", "bogus", 1])

    def test_counts_filter_bad_shape_is_a_query_error(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        for counts_filter in (
            ["not"],
            [">", "failures", "1"],
            ["nope", "failures", 1],
        ):
            with self.assertRaises(PuppetDBQueryError, msg=counts_filter):
                event_counts.apply_counts_filter(counts, counts_filter)

    def test_counts_filter_nested(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        filtered = event_counts.apply_counts_filter(
            counts,
            ["and", ["not", [">", "failures", 0]], ["=", "skips", 1]],
        )
        self.assertEqual([row["subject"]["title"] for row in filtered], ["b"])

    def test_counts_filter_on_a_field_summarize_never_emits(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        self.assertEqual(
            event_counts.apply_counts_filter(counts, ["=", "corrective_noops", 0]),
            counts,
        )
        self.assertEqual(
            event_counts.apply_counts_filter(counts, [">", "corrective_noops", 0]),
            [],
        )

    def test_aggregate(self):
        counts = event_counts.summarize(ROWS, "certname", "resource")
        totals = event_counts.aggregate(counts)
        self.assertEqual(totals["total"], 2)
        self.assertEqual(totals["failures"], 1)
        self.assertEqual(totals["skips"], 1)


if __name__ == "__main__":
    unittest.main()
