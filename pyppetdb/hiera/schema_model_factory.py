from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, create_model, constr


class SchemaModelFactory:
    def create(self, schema: dict[str, Any], name: str | None = None) -> type[BaseModel]:
        model_name = name or schema.get("title", "DynamicModel")
        return self._schema_object_to_model(schema, model_name)

    def _schema_object_to_model(
        self, schema: dict[str, Any], name: str
    ) -> type[BaseModel]:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields: dict[str, tuple[type[Any], Any]] = {}
        for field_name, field_schema in properties.items():
            field_type = self._schema_type_to_python(
                field_schema, f"{name}_{field_name}"
            )
            default = ... if field_name in required else None
            fields[field_name] = (field_type, default)

        return create_model(name, **fields)  # type: ignore[arg-type]

    def _schema_type_to_python(
        self, field_schema: dict[str, Any], name_hint: str
    ) -> type[Any]:
        if "enum" in field_schema:
            return Literal[tuple(field_schema["enum"])]  # type: ignore[misc]

        if "pattern" in field_schema and field_schema.get("type") == "string":
            return constr(pattern=field_schema["pattern"])

        type_name = field_schema.get("type")
        if type_name == "string":
            return str
        if type_name == "integer":
            return int
        if type_name == "number":
            return float
        if type_name == "boolean":
            return bool
        if type_name == "object":
            return self._schema_object_to_model(field_schema, name_hint)
        if type_name == "array":
            item_schema = field_schema.get("items", {"type": "string"})
            item_type = self._schema_type_to_python(item_schema, f"{name_hint}_item")
            if field_schema.get("uniqueItems"):
                return set[item_type]  # type: ignore[misc]
            return list[item_type]  # type: ignore[misc]
        return Any
