import importlib
from logging import Logger

from pyhiera import PyHieraAsync

from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.hiera.backend import PyHieraBackendCrudHieraLevelDataAsync
from pyppetdb.hiera.key_model_utils import KEY_MODEL_STATIC_PREFIX
from pyppetdb.hiera.key_model_utils import prefixed_key_model_id


class PyHiera:
    def __init__(
        self,
        log: Logger,
        crud_hiera_level_data: CrudHieraLevelData,
        hiera_level_ids: list[str],
        hiera_config: ConfigAppHiera,
    ):
        self._log = log
        self._hiera = PyHieraAsync()
        self._register_static_key_models()
        self._load_plugins(hiera_config=hiera_config)
        self._hiera.backend_add(
            PyHieraBackendCrudHieraLevelDataAsync(
                log=log,
                identifier="curd_hiera_level_data",
                crud_hiera_level_data=crud_hiera_level_data,
                priority=10,
                hierarchy=hiera_level_ids,
            )
        )

    @property
    def log(self):
        return self._log

    @property
    def hiera(self) -> PyHieraAsync:
        return self._hiera

    def _register_static_key_models(self) -> None:
        for key, model_type in list(self._hiera.key_models.items()):
            if key.startswith(KEY_MODEL_STATIC_PREFIX):
                continue
            prefixed_id = prefixed_key_model_id(KEY_MODEL_STATIC_PREFIX, key)
            self._hiera.key_model_add(prefixed_id, model_type)
            self._hiera.key_model_delete(key)

    def _load_plugins(
        self,
        hiera_config: ConfigAppHiera,
    ) -> None:
        if not hiera_config.keyModels:
            return

        for item in hiera_config.keyModels:
            if ":" in item:
                module_suffix, keys_str = item.split(":", 1)
                keys_to_load = keys_str.split(",")
            else:
                module_suffix = item
                keys_to_load = None

            module_name = f"pyppetdb_{module_suffix}"
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                self._log.warning(f"Failed to load Hiera plugin module: {module_name}")
                continue

            key_models = getattr(module, "key_models", {})
            for key, model_type in key_models.items():
                if keys_to_load and key not in keys_to_load:
                    continue

                prefixed_id = f"{KEY_MODEL_STATIC_PREFIX}{module_suffix}:{key}"
                self._hiera.key_model_add(prefixed_id, model_type)
