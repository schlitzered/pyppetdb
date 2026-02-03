from typing import Any
from typing import Optional

from pyhiera.errors import PyHieraError
from pyhiera.errors import PyHieraBackendError
from pyhiera.backends import PyHieraBackendBase
from pyhiera.backends import PyHieraBackendAsync
from pyhiera.backends import PyHieraBackendSync
from pyhiera.keys import PyHieraKeyBase
from pyhiera.keys import PyHieraKeyString
from pyhiera.keys import PyHieraKeyInt
from pyhiera.keys import PyHieraKeyFloat
from pyhiera.keys import PyHieraKeyBool
from pyhiera.keys import PyHieraModelDataBase
from pyhiera.models import PyHieraModelBackendData


class PyHieraKeyModels:
    def __init__(
        self,
        models: Optional[dict[str, type[PyHieraKeyBase]]] = None,
    ):
        if models is None:
            models = {
                "SimpleString": PyHieraKeyString,
                "SimpleInt": PyHieraKeyInt,
                "SimpleFloat": PyHieraKeyFloat,
                "SimpleBool": PyHieraKeyBool,
            }
        self._models = models

    @property
    def models(self) -> dict[str, type[PyHieraKeyBase]]:
        return self._models

    def add(self, key: str, model: type[PyHieraKeyBase]):
        self._models[key] = model

    def delete(self, key: str):
        try:
            del self._models[key]
        except KeyError:
            raise PyHieraError(f"Key model {key} not found")

    def get(self, key: str) -> type[PyHieraKeyBase]:
        try:
            return self._models[key]
        except KeyError:
            raise PyHieraError(f"Invalid key model {key}")


class PyHieraKeys:
    def __init__(self, key_models: PyHieraKeyModels):
        self._key_models = key_models
        self._keys: dict[str, PyHieraKeyBase] = {}

    @property
    def keys(self) -> dict[str, PyHieraKeyBase]:
        return self._keys

    def add(self, key: str, hiera_key: str):
        self._keys[key] = self._key_models.get(hiera_key)()

    def delete(self, key: str):
        try:
            del self._keys[key]
        except KeyError:
            raise PyHieraError(f"Key {key} not found")

    def validate(
        self,
        key: str,
        data: dict,
        sources: Optional[list[PyHieraModelBackendData]] = None,
    ) -> PyHieraModelDataBase:
        try:
            if sources:
                return self._keys[key].model(data=data, sources=sources)
            else:
                return self._keys[key].model(data=data)
        except KeyError:
            raise PyHieraError(f"Key {key} not found")
        except ValueError as err:
            raise PyHieraError(f"Invalid data for key {key}: {err}")


class PyHieraBackendsBase:
    def __init__(self):
        self._backends_list: list[PyHieraBackendBase] = []
        self._backends_dict: dict[str, PyHieraBackendBase] = {}

    @property
    def backends(self) -> list[PyHieraBackendBase]:
        return self._backends_list

    def add(self, backend: PyHieraBackendBase):
        if backend.identifier in self._backends_dict:
            raise PyHieraError(
                f"Backend with identifier {backend.identifier} already exists"
            )
        for _backend in self._backends_dict.values():
            if _backend.priority == backend.priority:
                raise PyHieraError(
                    f"Backend {backend.identifier} has same priority as {_backend.identifier}"
                )
        self._backends_dict[backend.identifier] = backend
        self._recreate_list()

    def delete(self, identifier: str):
        try:
            del self._backends_dict[identifier]
            self._recreate_list()
        except KeyError:
            raise PyHieraError(f"Backend with identifier {identifier} not found")

    def get(self, identifier: str) -> PyHieraBackendBase:
        try:
            return self._backends_dict[identifier]
        except KeyError:
            raise PyHieraError(f"Backend {identifier} not found")

    def _recreate_list(self):
        self._backends_list = list(self._backends_dict.values())
        self._backends_list.sort(key=lambda backend: backend.priority)


class PyHieraBackendsSync(PyHieraBackendsBase):
    def __init__(self):
        super().__init__()
        self._backends_list: list[PyHieraBackendSync] = []
        self._backends_dict: dict[str, PyHieraBackendSync] = {}


class PyHieraBackendsAsync(PyHieraBackendsBase):
    def __init__(self):
        super().__init__()
        self._backends_list: list[PyHieraBackendAsync] = []
        self._backends_dict: dict[str, PyHieraBackendAsync] = {}

    @property
    def backends(self) -> list[PyHieraBackendAsync]:
        return self._backends_list

    def get(self, identifier: str) -> PyHieraBackendAsync:
        try:
            return self._backends_dict[identifier]
        except KeyError:
            raise PyHieraError(f"Backend {identifier} not found")


class PyHieraBase:
    def __init__(self):
        self._key_models = PyHieraKeyModels()
        self._keys = PyHieraKeys(self._key_models)
        self._backends = PyHieraBackendsBase()

    @property
    def keys(self) -> dict[str, PyHieraKeyBase]:
        return self._keys.keys

    @property
    def key_models(self) -> dict[str, type[PyHieraKeyBase]]:
        return self._key_models.models

    def key_model_add(self, key: str, model: type[PyHieraKeyBase]):
        self._key_models.add(key, model)

    def key_model_delete(self, key: str):
        self._key_models.delete(key)

    def backend_add(self, backend: PyHieraBackendSync):
        self._backends.add(backend)

    def backend_delete(self, identifier: str):
        self._backends.delete(identifier)

    def key_add(self, key: str, hiera_key: str):
        self._keys.add(key, hiera_key)

    def key_delete(self, key: str):
        self._keys.delete(key)

    def key_data_validate(
        self,
        key: str,
        data: dict,
        sources: Optional[list[PyHieraModelBackendData]] = None,
    ) -> PyHieraModelDataBase:
        return self._keys.validate(key, data, sources=sources)

    def key_data_add(
        self,
        backend_identifier: str,
        key: str,
        data: Any,
        level: str,
        facts: dict[str, str],
    ):
        raise NotImplementedError

    def key_data_get(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        raise NotImplementedError

    def key_data_get_merge(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        raise NotImplementedError

    def _key_data_get_merge(self, update, result):
        for key, value in update.items():
            if isinstance(value, dict):
                self._key_data_get_merge(value, result.setdefault(key, {}))
            elif isinstance(value, list):
                if key in result:
                    result[key].extend(value)
                else:
                    result[key] = value
            elif isinstance(value, set):
                if key in result:
                    result[key].update(value)
                else:
                    result[key] = value
            else:
                result[key] = value
        return result


class PyHieraAsync(PyHieraBase):
    def __init__(self):
        super().__init__()
        self._backends = PyHieraBackendsAsync()

    def backend_add(self, backend: PyHieraBackendAsync):
        self._backends.add(backend)

    async def key_data_add(
        self,
        backend_identifier: str,
        key: str,
        data: Any,
        level: str,
        facts: dict[str, str],
    ):
        data = self.key_data_validate(key, data)
        backend = self._backends.get(backend_identifier)
        await backend.key_data_add(key, data, level, facts)

    async def key_data_get(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        if key not in self.keys:
            raise PyHieraError(f"Key {key} not found")
        for backend in self._backends.backends:
            data = await backend.key_data_get(key, facts)
            if data:
                if include_sources:
                    return self.key_data_validate(key, data[0].data, sources=[data[0]])
                else:
                    return self.key_data_validate(key, data[0].data)
        raise PyHieraBackendError("No data found")

    async def key_data_get_merge(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        if key not in self.keys:
            raise PyHieraError(f"Key {key} not found")

        data_points = []
        for backend in self._backends.backends:
            _data_points = await backend.key_data_get(key, facts)
            if _data_points:
                for data_point in _data_points:
                    if not isinstance(data_point.data, dict):
                        raise PyHieraBackendError(
                            f"Invalid data for key {key}, expected dict, got: {data_point.data}"
                        )
                    data_point.data = self.key_data_validate(
                        key, data_point.data
                    ).model_dump(exclude_none=True)["data"]
                    data_points.append(data_point)

        if not data_points:
            raise PyHieraBackendError("No data found")

        merged_data = {}
        for data_point in reversed(data_points):
            merged_data = self._key_data_get_merge(data_point.data, merged_data)

        if include_sources:
            return self.key_data_validate(key, merged_data, sources=data_points)
        else:
            return self.key_data_validate(key, merged_data)


class PyHieraSync(PyHieraBase):
    def __init__(self):
        super().__init__()
        self._backends = PyHieraBackendsSync()

    def key_data_add(
        self,
        backend_identifier: str,
        key: str,
        data: Any,
        level: str,
        facts: dict[str, str],
    ):
        data = self.key_data_validate(key, data)
        backend = self._backends.get(backend_identifier)
        backend.key_data_add(key, data, level, facts)

    def key_data_get(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        if key not in self.keys:
            raise PyHieraError(f"Key {key} not found")
        for backend in self._backends.backends:
            data = backend.key_data_get(key, facts)
            if data:
                if include_sources:
                    return self.key_data_validate(key, data[0].data, sources=[data[0]])
                else:
                    return self.key_data_validate(key, data[0].data)
        raise PyHieraBackendError("No data found")

    def key_data_get_merge(
        self,
        key: str,
        facts: dict[str, str],
        include_sources: bool = True,
    ) -> PyHieraModelDataBase:
        if key not in self.keys:
            raise PyHieraError(f"Key {key} not found")

        data_points = []
        for backend in self._backends.backends:
            _data_points = backend.key_data_get(key, facts)
            if _data_points:
                for data_point in _data_points:
                    if not isinstance(data_point.data, dict):
                        raise PyHieraBackendError(
                            f"Invalid data for key {key}, expected dict, got: {data_point.data}"
                        )
                    data_point.data = self.key_data_validate(
                        key, data_point.data
                    ).model_dump(exclude_none=True)["data"]
                    data_points.append(data_point)

        if not data_points:
            raise PyHieraBackendError("No data found")

        merged_data = {}
        for data_point in reversed(data_points):
            merged_data = self._key_data_get_merge(data_point.data, merged_data)

        if include_sources:
            return self.key_data_validate(key, merged_data, sources=data_points)
        else:
            return self.key_data_validate(key, merged_data)
