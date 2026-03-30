import unittest
from pyppetdb.crud.mixins import (
    FilterMixIn,
    ProjectionMixIn,
    SortMixIn,
    Format,
    PaginationSkipMixIn,
)
import pymongo


class TestCrudMixinsUnit(unittest.TestCase):
    def test_filter_boolean(self):
        query = {}
        FilterMixIn._filter_boolean(query, "active", "true")
        self.assertEqual(query["active"], True)

        query = {}
        FilterMixIn._filter_boolean(query, "active", "0")
        self.assertEqual(query["active"], False)

        query = {}
        FilterMixIn._filter_boolean(query, "active", None)
        self.assertEqual(query, {})

    def test_filter_list(self):
        query = {}
        FilterMixIn._filter_list(query, "tags", "a,b,c")
        self.assertIn("$in", query["tags"])
        self.assertEqual(set(query["tags"]["$in"]), {"a", "b", "c"})

        query = {}
        FilterMixIn._filter_list(query, "tags", ["a", "b"])
        self.assertEqual(query["tags"], {"$in": ["a", "b"]})

    def test_filter_re(self):
        query = {}
        FilterMixIn._filter_re(query, "id", "node.*")
        self.assertEqual(query["id"], {"$regex": "node.*"})

        query = {}
        FilterMixIn._filter_re(query, "id", "node.*", list_filter=["node1"])
        self.assertEqual(query["id"], {"$regex": "node.*", "$in": ["node1"]})

    def test_filter_literal(self):
        query = {}
        FilterMixIn._filter_literal(query, "status", "active")
        self.assertEqual(query["status"], "active")

        query = {}
        FilterMixIn._filter_literal(query, "status", "active", list_filter=["active"])
        self.assertEqual(query["status"], {"$eq": "active", "$in": ["active"]})

    def test_filter_complex_search(self):
        query = {}
        complex_search = ["osfamily:eq:str:RedHat"]
        FilterMixIn._filter_complex_search(query, "facts", complex_search)
        self.assertEqual(query["facts.osfamily"], {"$eq": "RedHat"})

        query = {}
        complex_search = ["uptime:gt:int:100"]
        FilterMixIn._filter_complex_search(query, "facts", complex_search)
        self.assertEqual(query["facts.uptime"], {"$gt": 100})

        query = {}
        complex_search = ["enabled:eq:bool:true"]
        FilterMixIn._filter_complex_search(query, "facts", complex_search)
        self.assertEqual(query["facts.enabled"], {"$eq": True})

        query = {}
        complex_search = ["tags:in:str:a,b,c"]
        FilterMixIn._filter_complex_search(query, "facts", complex_search)
        self.assertEqual(query["facts.tags"], {"$in": ["a", "b", "c"]})

    def test_format_multi(self):
        result = Format._format_multi([{"id": "1"}], count=1)
        self.assertEqual(result["meta"]["result_size"], 1)
        self.assertEqual(result["result"][0]["id"], "1")

    def test_pagination_skip(self):
        self.assertEqual(PaginationSkipMixIn._pagination_skip(2, 10), 20)

    def test_projection(self):
        # Test basic projection
        fields = ["id", "facts.os", "facts.role"]
        expected = {"id": 1, "facts.os": 1, "facts.role": 1}
        self.assertEqual(ProjectionMixIn._projection(fields), expected)

        # Test redundant fields (if facts is projected, facts.os is redundant)
        fields = ["id", "facts", "facts.os"]
        expected = {"id": 1, "facts": 1}
        self.assertEqual(ProjectionMixIn._projection(fields), expected)

        # Test empty
        self.assertIsNone(ProjectionMixIn._projection([]))

    def test_sort(self):
        self.assertEqual(
            SortMixIn._sort("id", "ascending"), [("id", pymongo.ASCENDING)]
        )
        self.assertEqual(
            SortMixIn._sort("id", "descending"), [("id", pymongo.DESCENDING)]
        )

    def test_format(self):
        item = {"_id": "someid", "id": "myid", "foo": "bar"}
        formatted = Format._format(item)
        self.assertNotIn("_id", formatted)
        self.assertEqual(formatted["id"], "myid")
