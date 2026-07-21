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

from pydantic import ValidationError

from pyppetdb.hiera.schema_model_factory import SchemaModelFactory


class TestSchemaModelFactory(unittest.TestCase):
    def _model(self, prop_schema, required=True):
        schema = {
            "type": "object",
            "required": ["v"] if required else [],
            "properties": {"v": prop_schema},
        }
        return SchemaModelFactory().create(schema, "M")

    def test_type_is_enforced(self):
        model = self._model({"type": "integer"})
        self.assertEqual(model(v=5).v, 5)
        with self.assertRaises(ValidationError):
            model(v=[1, 2])

    def test_enum_is_enforced(self):
        model = self._model({"enum": ["a", "b"]})
        self.assertEqual(model(v="a").v, "a")
        with self.assertRaises(ValidationError):
            model(v="c")

    def test_pattern_is_enforced(self):
        model = self._model({"type": "string", "pattern": r"^\d+$"})
        self.assertEqual(model(v="123").v, "123")
        with self.assertRaises(ValidationError):
            model(v="abc")

    def test_required_vs_optional(self):
        with self.assertRaises(ValidationError):
            self._model({"type": "string"}, required=True)()
        self.assertIsNone(self._model({"type": "string"}, required=False)().v)

    def test_array_unique_items_becomes_set(self):
        model = self._model(
            {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
        )
        self.assertEqual(model(v=["a", "a", "b"]).v, {"a", "b"})

    def test_minimum_maximum_are_not_enforced(self):
        model = self._model({"type": "integer", "minimum": 1, "maximum": 10})
        self.assertEqual(model(v=99999).v, 99999)
        self.assertEqual(model(v=-5).v, -5)

    def test_min_max_length_are_not_enforced(self):
        model = self._model({"type": "string", "minLength": 5, "maxLength": 8})
        self.assertEqual(model(v="ab").v, "ab")
        self.assertEqual(model(v="waytoolongvalue").v, "waytoolongvalue")

    def test_format_is_not_enforced(self):
        model = self._model({"type": "string", "format": "email"})
        self.assertEqual(model(v="not-an-email").v, "not-an-email")


if __name__ == "__main__":
    unittest.main()
