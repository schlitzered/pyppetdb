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

from pyppetdb.pdbquery.ast import Query
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.paging import parse_paging


class TestParsePaging(unittest.TestCase):
    def test_defaults(self):
        paging = parse_paging({})
        self.assertIsNone(paging.limit)
        self.assertIsNone(paging.offset)
        self.assertIsNone(paging.order_by)
        self.assertFalse(paging.include_total)

    def test_order_by_json(self):
        paging = parse_paging(
            {"order_by": '[{"field":"certname"},{"field":"status","order":"desc"}]'}
        )
        self.assertEqual(paging.order_by, [("certname", 1), ("status", -1)])

    def test_malformed_order_by(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            parse_paging({"order_by": '[{"field":"status" "order":"DESC"}]'})
        self.assertIn("expected a JSON array of maps", str(ctx.exception))

    def test_order_by_not_a_list(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_paging({"order_by": '{"field":"certname"}'})

    def test_bad_order_direction(self):
        with self.assertRaises(PuppetDBQueryError):
            parse_paging({"order_by": '[{"field":"certname","order":"sideways"}]'})

    def test_limit_must_be_positive(self):
        for value in ("0", "-1", "1.1", "abc"):
            with self.assertRaises(PuppetDBQueryError, msg=value):
                parse_paging({"limit": value})

    def test_limit_accepted(self):
        self.assertEqual(parse_paging({"limit": "25"}).limit, 25)

    def test_offset_zero_allowed(self):
        self.assertEqual(parse_paging({"offset": "0"}).offset, 0)

    def test_include_total(self):
        self.assertTrue(parse_paging({"include_total": "true"}).include_total)
        self.assertFalse(parse_paging({"include_total": "false"}).include_total)
        with self.assertRaises(PuppetDBQueryError):
            parse_paging({"include_total": "maybe"})

    def test_apply_overrides_query(self):
        query = Query(entity="nodes", limit=1)
        parse_paging({"limit": "5", "offset": "2"}).apply(query)
        self.assertEqual(query.limit, 5)
        self.assertEqual(query.offset, 2)

    def test_apply_keeps_query_values_when_unset(self):
        query = Query(entity="nodes", limit=7)
        parse_paging({}).apply(query)
        self.assertEqual(query.limit, 7)


if __name__ == "__main__":
    unittest.main()
