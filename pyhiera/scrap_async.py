import asyncio
import os
from typing import Optional

from pydantic import BaseModel

from pyhiera import PyHieraAsync
from pyhiera import PyHieraBackendYamlAsync
from pyhiera import PyHieraKeyBase
from pyhiera import PyHieraModelDataBase


class PyHieraKeyDataComplexLevelB(BaseModel):
    blarg: Optional[str] = None
    other: Optional[str] = None
    blub: Optional[set[str]] = None


class PyHieraKeyDataComplexLevel(BaseModel):
    a: Optional[str] = None
    b: Optional[PyHieraKeyDataComplexLevelB] = None


class PyHieraKeyDataComplex(PyHieraModelDataBase):
    data: PyHieraKeyDataComplexLevel


class PyHieraKeyComplex(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "complex data"
        self._model = PyHieraKeyDataComplex


# Hierarchy levels
# 1. stage/{stage}/.yaml
# 2. common.yaml
# PyHieraBackendYaml appends .yaml to the level string.
hierarchy = [
    "stage/{stage}.yaml",
    "common.yaml",
]

# Base path for data
base_path = os.path.join(os.getcwd(), "test_data")
print(f"Base path: {base_path}")

if not os.path.exists(base_path):
    os.makedirs(base_path)

# Initialize backend
backend = PyHieraBackendYamlAsync(
    identifier="test_yaml",
    priority=1,
    config={"path": base_path},
    hierarchy=hierarchy,
)


async def main():
    pyhiera = PyHieraAsync()
    pyhiera.key_model_add(key="Complex", model=PyHieraKeyComplex)
    pyhiera.backend_add(backend)
    pyhiera.key_add(key="db_host", hiera_key="SimpleString")
    pyhiera.key_add(key="complex", hiera_key="Complex")

    print("Inserting test data...")
    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="db_host",
        data="127.0.0.1",
        level="common.yaml",
        facts={},
    )
    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="db_host",
        data="127.0.0.2",
        level="stage/{stage}.yaml",
        facts={"stage": "prod"},
    )
    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="db_host",
        data="127.0.0.3",
        level="stage/{stage}.yaml",
        facts={"stage": "dev"},
    )

    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="complex",
        data={
            "a": "common",
            "b": {"blarg": "1", "a": 123, "other": "val", "blub": ["a", "b", "c"]},
        },
        level="common.yaml",
        facts={},
    )
    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="complex",
        data={"b": {"blarg": "2", "blub": ["c", "d"]}},
        level="stage/{stage}.yaml",
        facts={"stage": "dev"},
    )
    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="complex",
        data={"a": "prod", "b": {"blarg": "3", "blub": ["c", "d", "e"]}},
        level="stage/{stage}.yaml",
        facts={"stage": "prod"},
    )

    print("\nRetrieving data...")

    async def get_and_print(key, facts):
        results = await backend.key_data_get(key, facts)
        print(f"Key: {key}, Facts: {facts}")
        if results:
            for r in results:
                print(f"  Found in level '{r.level}': {r.data}")
        else:
            print("  Not found")

    await get_and_print("db_host", {"stage": "dev"})
    await get_and_print("complex", {"stage": "dev"})

    print("\nPyHiera key_data_get:")
    print(
        f"db_host (stage: blarg): {await pyhiera.key_data_get('db_host', {'stage': 'blarg'})}"
    )
    print(
        f"complex (stage: blarg): {await pyhiera.key_data_get('complex', {'stage': 'blarg'})}"
    )
    print(
        f"db_host (stage: dev): {await pyhiera.key_data_get('db_host', {'stage': 'dev'})}"
    )
    print(
        f"complex (stage: dev): {await pyhiera.key_data_get('complex', {'stage': 'dev'})}"
    )

    print("\nPyHiera key_data_get_merge:")
    print(
        "complex (stage: dev): "
        f"{await pyhiera.key_data_get_merge('complex', {'stage': 'dev'})}"
    )
    print(
        "complex (stage: prod): "
        f"{await pyhiera.key_data_get_merge('complex', {'stage': 'prod'})}"
    )
    print(
        "complex (stage: assdasd): "
        f"{await pyhiera.key_data_get_merge('complex', {'stage': 'assdasd'})}"
    )


if __name__ == "__main__":
    asyncio.run(main())
