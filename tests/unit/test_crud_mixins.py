import unittest
from pyppetdb.crud.mixins import FilterMixIn, ProjectionMixIn, SortMixIn, Format, PaginationSkipMixIn
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
        self.assertEqual(SortMixIn._sort("id", "ascending"), [("id", pymongo.ASCENDING)])
        self.assertEqual(SortMixIn._sort("id", "descending"), [("id", pymongo.DESCENDING)])

    def test_format(self):
        item = {"_id": "someid", "id": "myid", "foo": "bar"}
        formatted = Format._format(item)
        self.assertNotIn("_id", formatted)
        self.assertEqual(formatted["id"], "myid")
