import logging
from typing import Any
from pyppetdb.nodes_secrets_redactor import NodesSecretsRedactor


class NodesCatalogsRedactor:
    def __init__(self, log: logging.Logger, redactor: NodesSecretsRedactor):
        self.log = log
        self._redactor = redactor

    def redact(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        catalog = data.get("catalog")
        if not isinstance(catalog, dict):
            return data

        for resources_key in ["resources", "resources_exported"]:
            resources = catalog.get(resources_key)
            if isinstance(resources, list):
                for resource in resources:
                    if not isinstance(resource, dict):
                        continue
                    parameters = resource.get("parameters")
                    if isinstance(parameters, dict):
                        # Redact only values in parameters, and we use the base redactor for the value
                        # Note: we don't redact the keys of the parameters here.
                        for k, v in parameters.items():
                            parameters[k] = self._redactor.redact(v)
        return data
