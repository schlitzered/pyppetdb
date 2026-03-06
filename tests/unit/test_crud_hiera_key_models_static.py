import unittest
from unittest.mock import MagicMock
import logging
from pyppetdb.crud.hiera_key_models_static import CrudHieraKeyModelsStatic
from pyppetdb.errors import QueryParamValidationError

class TestCrudHieraKeyModelsStaticUnit(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_pyhiera = MagicMock()
        self.crud = CrudHieraKeyModelsStatic(self.mock_config, self.log, self.mock_pyhiera)

    def test_get_success(self):
        mock_model_type = MagicMock()
        mock_model_type.return_value.description = "desc"
        self.mock_pyhiera.hiera.key_models = {"static:test": mock_model_type}
        
        result = self.crud.get(_id="static:test")
        self.assertEqual(result.id, "static:test")
        self.assertEqual(result.description, "desc")

    def test_get_not_found(self):
        self.mock_pyhiera.hiera.key_models = {}
        with self.assertRaises(QueryParamValidationError):
            self.crud.get(_id="static:unknown")

    def test_get_invalid_prefix(self):
        with self.assertRaises(QueryParamValidationError):
            self.crud.get(_id="dynamic:test")

    def test_search(self):
        mock_model1 = MagicMock()
        mock_model1.return_value.description = "desc1"
        mock_model2 = MagicMock()
        mock_model2.return_value.description = "desc2"
        
        self.mock_pyhiera.hiera.key_models = {
            "static:test1": mock_model1,
            "static:test2": mock_model2,
            "dynamic:other": MagicMock()
        }
        
        # Test basic search
        result = self.crud.search(_id="test1")
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].id, "static:test1")
        
        # Test sort
        result = self.crud.search(sort="id", sort_order="descending")
        self.assertEqual(result.result[0].id, "static:test2")
        
        # Test pagination
        result = self.crud.search(limit=1)
        self.assertEqual(len(result.result), 1)

    def test_build_item_with_model_field(self):
        mock_model_type = MagicMock()
        mock_model = mock_model_type.return_value
        mock_model.description = "desc"
        mock_model.model.model_json_schema.return_value = {"properties": {}}
        
        item = self.crud._build_item("static:test", mock_model_type, fields=["model"])
        self.assertEqual(item.id, "static:test")
        self.assertEqual(item.model, {"properties": {}})

    def test_search_invalid_regex(self):
        with self.assertRaises(QueryParamValidationError):
            self.crud.search(_id="[")
