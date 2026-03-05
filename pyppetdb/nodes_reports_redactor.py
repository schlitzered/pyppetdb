import logging
from typing import Any
from pyppetdb.nodes_secrets_redactor import NodesSecretsRedactor


class NodesReportsRedactor:
    def __init__(self, log: logging.Logger, redactor: NodesSecretsRedactor):
        self.log = log
        self._redactor = redactor

    def redact(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        report = data.get("report")
        if not isinstance(report, dict):
            return data

        # 1. report.logs: only redact "message" field of each object
        logs = report.get("logs")
        if isinstance(logs, list):
            for log_entry in logs:
                if isinstance(log_entry, dict) and "message" in log_entry:
                    log_entry["message"] = self._redactor.redact(log_entry["message"])

        # 2. report.resources.[].events.[].new_value, old_value, message
        resources = report.get("resources")
        if isinstance(resources, list):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                events = resource.get("events")
                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, dict):
                            continue
                        for field in ["new_value", "old_value", "message"]:
                            if field in event:
                                event[field] = self._redactor.redact(event[field])

        return data
