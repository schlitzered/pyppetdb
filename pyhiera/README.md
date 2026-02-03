# PyHiera

PyHiera is a small, Puppet-Hiera-inspired parameter lookup engine. It supports
hierarchical data lookup with sync and async backends.

## Install

```bash
pip install pyhiera
```

## Basic usage (sync)

```python
import os
from pyhiera import PyHieraSync, PyHieraBackendYamlSync

hierarchy = [
    "stage/{stage}.yaml",
    "common.yaml",
]

base_path = os.path.join(os.getcwd(), "test_data")
backend = PyHieraBackendYamlSync(
    identifier="test_yaml",
    priority=1,
    config={"path": base_path},
    hierarchy=hierarchy,
)

pyhiera = PyHieraSync()
pyhiera.backend_add(backend)
pyhiera.key_add(key="db_host", hiera_key="SimpleString")

pyhiera.key_data_add(
    backend_identifier="test_yaml",
    key="db_host",
    data="127.0.0.1",
    level="common.yaml",
    facts={},
)

print(pyhiera.key_data_get("db_host", {"stage": "dev"}))
```

## Basic usage (async)

```python
import asyncio
import os
from pyhiera import PyHieraAsync, PyHieraBackendYamlAsync

hierarchy = [
    "stage/{stage}.yaml",
    "common.yaml",
]

base_path = os.path.join(os.getcwd(), "test_data")
backend = PyHieraBackendYamlAsync(
    identifier="test_yaml",
    priority=1,
    config={"path": base_path},
    hierarchy=hierarchy,
)


async def main():
    pyhiera = PyHieraAsync()
    pyhiera.backend_add(backend)
    pyhiera.key_add(key="db_host", hiera_key="SimpleString")

    await pyhiera.key_data_add(
        backend_identifier="test_yaml",
        key="db_host",
        data="127.0.0.1",
        level="common.yaml",
        facts={},
    )

    print(await pyhiera.key_data_get("db_host", {"stage": "dev"}))


if __name__ == "__main__":
    asyncio.run(main())
```

## Custom keys and models

Keys wrap Pydantic models. Define your model by extending
`PyHieraModelDataBase`, then register a `PyHieraKeyBase` that points at it.

```python
from typing import Optional
from pydantic import BaseModel
from pyhiera import PyHieraKeyBase, PyHieraModelDataBase


class AppConfigData(BaseModel):
    host: str
    port: int
    mode: Optional[str] = None


class AppConfigModel(PyHieraModelDataBase):
    data: AppConfigData


class AppConfigKey(PyHieraKeyBase):
    def __init__(self):
        super().__init__()
        self._description = "app config"
        self._model = AppConfigModel
```

Register it and use it like any other key:

```python
pyhiera.key_model_add(key="AppConfig", model=AppConfigKey)
pyhiera.key_add(key="app_config", hiera_key="AppConfig")
```

## Custom backends

Backends implement add/get for a hierarchy. Choose sync or async by extending
`PyHieraBackendSync` or `PyHieraBackendAsync`.

### Sync backend example

```python
from typing import Any
from pyhiera.backends import PyHieraBackendSync
from pyhiera.models import PyHieraModelBackendData


class PyHieraBackendMemorySync(PyHieraBackendSync):
    def init(self):
        self._data = {}

    def _key_data_add(self, key, data, level):
        self._data.setdefault(level, {})
        self._data[level][key] = data.model_dump(exclude_none=True)["data"]

    def _key_data_get(self, key, levels):
        result = []
        for level in levels:
            if key in self._data.get(level, {}):
                result.append(
                    PyHieraModelBackendData(
                        identifier=self.identifier,
                        priority=self.priority,
                        key=key,
                        level=level,
                        data=self._data[level][key],
                    )
                )
        return result
```

### Async backend example

```python
from pyhiera.backends import PyHieraBackendAsync
from pyhiera.models import PyHieraModelBackendData


class PyHieraBackendMemoryAsync(PyHieraBackendAsync):
    def init(self):
        self._data = {}

    async def _key_data_add(self, key, data, level):
        self._data.setdefault(level, {})
        self._data[level][key] = data.model_dump(exclude_none=True)["data"]

    async def _key_data_get(self, key, levels):
        result = []
        for level in levels:
            if key in self._data.get(level, {}):
                result.append(
                    PyHieraModelBackendData(
                        identifier=self.identifier,
                        priority=self.priority,
                        key=key,
                        level=level,
                        data=self._data[level][key],
                    )
                )
        return result
```

## See also

- `scrap.py` and `scrap_async.py` for end-to-end examples.
