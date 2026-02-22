from logging import Logger

from pyhiera import PyHieraAsync

from pyppetdb.config import ConfigHiera
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.pyhiera.backend import PyHieraBackendCrudHieraLevelDataAsync
from pyppetdb.pyhiera.key_model_utils import KEY_MODEL_STATIC_PREFIX
from pyppetdb.pyhiera.key_model_utils import prefixed_key_model_id


class PyHiera:
    def __init__(
        self,
        log: Logger,
        config: ConfigHiera,
        crud_hiera_level_data: CrudHieraLevelData,
        hiera_level_ids: list[str],
    ):
        self._log = log
        self._config = config
        self._hiera = PyHieraAsync()
        self._register_static_key_models()
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
    def config(self) -> ConfigHiera:
        return self._config

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
