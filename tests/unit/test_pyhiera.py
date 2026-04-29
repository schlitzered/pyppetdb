import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pydantic import BaseModel
from pyppetdb.hiera.schema_model_factory import SchemaModelFactory
from pyppetdb.hiera.key_model_utils import prefixed_key_model_id
from pyppetdb.hiera.backend import PyHieraBackendCrudHieraLevelDataAsync
from pyppetdb.hiera import PyHiera


class TestHieraUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")

    def test_schema_model_factory(self):
        factory = SchemaModelFactory()

        # Test basic string/int schema
        schema = {
            "title": "User",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }

        model_cls = factory.create(schema)
        self.assertTrue(issubclass(model_cls, BaseModel))
        self.assertEqual(model_cls.__name__, "User")

        # Test instantiation
        user = model_cls(name="Alice", age=30)
        self.assertEqual(user.name, "Alice")
        self.assertEqual(user.age, 30)

        # Test required field
        with self.assertRaises(Exception):
            model_cls(age=30)

        # Test complex schema (nested object, array, enum)
        complex_schema = {
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {
                    "type": "object",
                    "properties": {"version": {"type": "string"}},
                },
            }
        }
        complex_model_cls = factory.create(complex_schema, name="ComplexModel")
        obj = complex_model_cls(
            status="active", tags=["a", "b"], metadata={"version": "1.0"}
        )
        self.assertEqual(obj.status, "active")
        self.assertEqual(obj.tags, ["a", "b"])
        self.assertEqual(obj.metadata.version, "1.0")

    def test_key_model_utils(self):
        # Test prefixed
        self.assertEqual(prefixed_key_model_id("static:", "mykey"), "static:mykey")

    async def test_pyhiera_backend(self):
        mock_crud = MagicMock()
        mock_crud.search = AsyncMock()

        # Mocking the return value of search
        mock_item = MagicMock()
        mock_item.priority = 100
        mock_item.level_id = "level1"
        mock_item.id = "doc1"
        mock_item.data = {"foo": "bar"}

        mock_result = MagicMock()
        mock_result.result = [mock_item]
        mock_crud.search.return_value = mock_result

        backend = PyHieraBackendCrudHieraLevelDataAsync(
            log=self.log,
            identifier="test_backend",
            crud_hiera_level_data=mock_crud,
            priority=10,
            hierarchy=["level1"],
        )

        results = await backend._key_data_get("mykey", ["level1"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].data, {"foo": "bar"})
        self.assertEqual(results[0].level, "level1/doc1")

        mock_crud.search.assert_called_once_with(
            key_id="mykey",
            _id_list=["level1"],
            sort="priority",
            sort_order="descending",
        )

    async def test_pyhiera_backend_expand_level(self):
        backend = PyHieraBackendCrudHieraLevelDataAsync(
            log=self.log,
            identifier="test_backend",
            crud_hiera_level_data=MagicMock(),
            priority=10,
            hierarchy=["{role}", "{pyppetdb.role}"],
        )

        # Flat fact
        level = backend._expand_level("{role}", {"role": "web"})
        self.assertEqual(level, "web")

        # Nested fact
        level = backend._expand_level("{pyppetdb.role}", {"pyppetdb.role": "db"})
        self.assertEqual(level, "db")

        # Missing nested fact
        with self.assertRaises(Exception) as cm:
            backend._expand_level("{pyppetdb.role}", {"other": "thing"})
        self.assertIn("'pyppetdb.role'", str(cm.exception))

    def test_pyhiera_init(self):
        from unittest.mock import patch

        mock_crud = MagicMock()

        with patch("pyppetdb.hiera.PyHieraAsync") as mock_pyhiera_async_cls:
            mock_hiera_instance = mock_pyhiera_async_cls.return_value
            mock_hiera_instance.key_models = {}

            PyHiera(
                log=self.log,
                crud_hiera_level_data=mock_crud,
                hiera_level_ids=["level1"],
            )

            # Verify backend was added
            self.assertEqual(mock_hiera_instance.backend_add.call_count, 1)
            added_backend = mock_hiera_instance.backend_add.call_args[0][0]
            self.assertIsInstance(added_backend, PyHieraBackendCrudHieraLevelDataAsync)
