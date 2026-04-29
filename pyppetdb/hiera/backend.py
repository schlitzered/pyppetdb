from logging import Logger


from pyhiera.backends import PyHieraBackendAsync
from pyhiera.errors import PyHieraBackendError
from pyhiera.models import PyHieraModelBackendData

from pyppetdb.crud.hiera_level_data import CrudHieraLevelData
from pyppetdb.helpers.hiera import HieraLevelFormatter


class PyHieraBackendCrudHieraLevelDataAsync(PyHieraBackendAsync):

    def __init__(
        self,
        log: Logger,
        identifier,
        crud_hiera_level_data: CrudHieraLevelData,
        priority,
        hierarchy,
    ):
        super().__init__(
            config={},
            identifier=identifier,
            priority=priority,
            hierarchy=hierarchy,
        )
        self._log = log
        self._crud_hiera_level_data = crud_hiera_level_data
        self._formatter = HieraLevelFormatter()

    @property
    def log(self):
        return self._log

    @property
    def crud_hiera_level_data(self) -> CrudHieraLevelData:
        return self._crud_hiera_level_data

    def _expand_level(self, level: str, facts: dict[str, str]) -> str:
        try:
            return self._formatter.format(level, **facts)
        except KeyError as err:
            raise PyHieraBackendError(f"missing facts to expand level {level}: {err}")

    async def _key_data_get(self, key, levels) -> list[PyHieraModelBackendData]:
        _results = list()
        _result = await self.crud_hiera_level_data.search(
            key_id=key,
            _id_list=levels,
            sort="priority",
            sort_order="descending",
        )
        for item in _result.result:
            _results.append(
                PyHieraModelBackendData(
                    identifier=self.identifier,
                    priority=item.priority,
                    key=key,
                    level=f"{item.level_id}/{item.id}",
                    data=item.data,
                )
            )
        return _results
