from pyhiera import PyHieraAsync

from pyppetdb.config import ConfigHiera


class PyHiera:
    def __init__(self, config: ConfigHiera):
        self._config = config
        self._hiera = PyHieraAsync()

    @property
    def config(self) -> ConfigHiera:
        return self._config

    @property
    def hiera(self) -> PyHieraAsync:
        return self._hiera
