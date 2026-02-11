from logging import Logger
from pyhiera import PyHieraAsync

from pyppetdb.config import ConfigHiera
from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.pyhiera.backend import PyHieraBackendCrudHieraLevelDataAsync


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
