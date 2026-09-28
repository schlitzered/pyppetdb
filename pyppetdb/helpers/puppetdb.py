# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import fnmatch
import functools
import hashlib
import json
import re
from datetime import UTC
from datetime import datetime
from typing import Optional

CATALOG_CONTENT_FIELDS = frozenset(
    {
        "resources",
        "resources_exported",
        "edges",
    }
)


def stable_hash(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def resource_hash(resource_type: str, title: str) -> str:
    return hashlib.sha1(f"{resource_type}\0{title}".encode("utf-8")).hexdigest()


def parse_wire_timestamp(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def normalise_resources(resources) -> list:
    if not isinstance(resources, list):
        return []
    normalised = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        item = dict(resource)
        item["exported"] = bool(resource.get("exported"))
        item["tags"] = resource.get("tags") or []
        item["parameters"] = resource.get("parameters") or {}
        item["resource"] = resource_hash(
            str(resource.get("type")), str(resource.get("title"))
        )
        normalised.append(item)
    return normalised


def normalise_edges(edges) -> list:
    if not isinstance(edges, list):
        return []
    normalised = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source") or {}
        target = edge.get("target") or {}
        normalised.append(
            {
                "relationship": edge.get("relationship"),
                "source_type": source.get("type"),
                "source_title": source.get("title"),
                "target_type": target.get("type"),
                "target_title": target.get("title"),
            }
        )
    return normalised


def normalise_package_inventory(packages) -> Optional[list]:
    if not isinstance(packages, list):
        return None
    normalised = []
    for package in packages:
        if isinstance(package, list) and len(package) >= 3:
            normalised.append([str(item) for item in package[:3]])
    return normalised


def normalise_catalog_inputs(inputs) -> list:
    if not isinstance(inputs, list):
        return []
    normalised = []
    for item in inputs:
        if isinstance(item, list) and len(item) >= 2:
            normalised.append([str(item[0]), str(item[1])])
    return normalised


def catalog_content_hash(resources, edges) -> str:
    return stable_hash({"resources": resources, "edges": edges})


RESOURCE_PARAM_MAX_VALUE_LEN = 512


def build_resource_params(resources, max_value_len: int = RESOURCE_PARAM_MAX_VALUE_LEN) -> list:
    seen = set()
    pairs = []
    if not isinstance(resources, list):
        return pairs
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        params = resource.get("parameters")
        if not isinstance(params, dict):
            continue
        for name, value in params.items():
            if isinstance(value, bool) or isinstance(value, (int, float)):
                pass
            elif isinstance(value, str):
                if len(value) > max_value_len:
                    continue
            else:
                continue
            key = (name, value)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"n": name, "v": value})
    return pairs


FACTS_INDEX_FIELD = "facts_index"
FACT_PATHS_FIELD = "fact_paths"
FACT_PATH_CACHE_SIZE = 100000
FACTS_INDEX_MAX_VALUE_LEN = 256
FACTS_INDEX_DEPTH = 3

POSITIONAL_SEGMENT = re.compile(r"^[0-9]+$")


def indexable_segment(segment: str) -> bool:
    if not segment or "\0" in segment or segment.startswith("$"):
        return False
    return POSITIONAL_SEGMENT.match(segment) is None


def indexable_fact_path(path: str) -> bool:
    return all(indexable_segment(segment) for segment in path.split("."))


GLOB_CHARS = ("*", "?", "[")


def _is_glob(entry: str) -> bool:
    return any(char in entry for char in GLOB_CHARS)


def _path_and_ancestors(path: str) -> list:
    segments = path.split(".")
    return [".".join(segments[:count]) for count in range(len(segments), 0, -1)]


class FactsIndexSpec:
    def __init__(
        self,
        max_value_len: int = FACTS_INDEX_MAX_VALUE_LEN,
        depth: int = FACTS_INDEX_DEPTH,
        deny=None,
    ):
        self._max_value_len = max_value_len
        self._depth = max(1, depth or 1)
        self._deny = tuple(deny or ())
        self._deny_patterns = tuple(
            re.compile(fnmatch.translate(entry)) if _is_glob(entry) else None
            for entry in self._deny
        )

    @property
    def max_value_len(self) -> int:
        return self._max_value_len

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def deny(self) -> tuple:
        return self._deny

    def denied(self, path: str) -> bool:
        candidates = _path_and_ancestors(path)
        for entry, pattern in zip(self._deny, self._deny_patterns):
            if pattern is None:
                if entry in candidates:
                    return True
            elif any(pattern.match(candidate) for candidate in candidates):
                return True
        return False

    def indexable_value(self, value) -> bool:
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            return len(value) <= self._max_value_len
        return False

    def indexable_path(self, path: str) -> bool:
        if not isinstance(path, str) or not path:
            return False
        if path.count(".") + 1 > self._depth:
            return False
        if not indexable_fact_path(path):
            return False
        return not self.denied(path)

    def indexable(self, path: str, value) -> bool:
        return self.indexable_path(path) and self.indexable_value(value)


def build_facts_index(
    facts,
    max_value_len: int = FACTS_INDEX_MAX_VALUE_LEN,
    depth: int = FACTS_INDEX_DEPTH,
    deny=None,
) -> list:
    entries = []
    if not isinstance(facts, dict):
        return entries
    spec = FactsIndexSpec(max_value_len=max_value_len, depth=depth, deny=deny)
    seen = set()
    for name, value in facts.items():
        start = len(entries)
        _index_fact(entries, seen, spec, name, value)
        if not any(entry["p"] == name for entry in entries[start:]):
            entries.insert(start, {"p": name})
    return entries


def _index_fact(entries: list, seen: set, spec: FactsIndexSpec, path: str, value):
    if isinstance(value, list):
        for item in value:
            _index_fact(entries, seen, spec, path, item)
        return
    if isinstance(value, dict):
        if path.count(".") + 1 >= spec.depth:
            return
        for key, item in value.items():
            _index_fact(entries, seen, spec, f"{path}.{key}", item)
        return
    _add_fact_entry(entries, seen, spec, path, value)


def _add_fact_entry(entries: list, seen: set, spec: FactsIndexSpec, path: str, value):
    if not spec.indexable(path, value):
        return
    key = (path, type(value).__name__, value)
    if key in seen:
        return
    seen.add(key)
    entries.append({"p": path, "v": value})


def walk_fact(value, path: list):
    if isinstance(value, dict):
        if not value:
            yield list(path), value
            return
        for key, item in value.items():
            yield from walk_fact(item, path + [key])
        return
    if isinstance(value, list):
        if not value:
            yield list(path), value
            return
        for index, item in enumerate(value):
            yield from walk_fact(item, path + [index])
        return
    yield list(path), value


def fact_value_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return "json"


def encode_fact_path(path: list, value_type: str) -> str:
    return json.dumps([path, value_type], separators=(",", ":"), ensure_ascii=False)


@functools.lru_cache(maxsize=FACT_PATH_CACHE_SIZE)
def _decoded_fact_path(entry: str) -> tuple:
    path, value_type = json.loads(entry)
    return tuple(path), value_type


def decode_fact_path(entry: str) -> tuple:
    path, value_type = _decoded_fact_path(entry)
    return list(path), value_type


def build_fact_paths(facts) -> list:
    if not isinstance(facts, dict):
        return []
    entries = set()
    for name, value in facts.items():
        for path, leaf in walk_fact(value, [name]):
            entries.add(encode_fact_path(path, fact_value_type(leaf)))
    return sorted(entries)


def dotted_fact_name(path: list) -> str:
    return ".".join(str(part) for part in path if not isinstance(part, int))


def _param_index(params: dict, max_value_len: int) -> list:
    out = []
    if not isinstance(params, dict):
        return out
    for name, value in params.items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            pass
        elif isinstance(value, str):
            if len(value) > max_value_len:
                continue
        else:
            continue
        out.append({"n": name, "v": value})
    return out


def build_resource_documents(
    node_id: str,
    placement: Optional[dict],
    environment: Optional[str],
    disabled: bool,
    resources,
    max_value_len: int = RESOURCE_PARAM_MAX_VALUE_LEN,
) -> list:
    docs = []
    if not isinstance(resources, list):
        return docs
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        params = resource.get("parameters") or {}
        docs.append(
            {
                "node_id": node_id,
                "placement": placement,
                "environment": environment,
                "disabled": disabled,
                "resource": resource.get("resource"),
                "type": resource.get("type"),
                "title": resource.get("title"),
                "exported": bool(resource.get("exported")),
                "tags": resource.get("tags") or [],
                "file": resource.get("file"),
                "line": resource.get("line"),
                "parameters": params,
                "params_index": _param_index(params, max_value_len),
            }
        )
    return docs


def build_edge_documents(
    node_id: str,
    placement: Optional[dict],
    environment: Optional[str],
    disabled: bool,
    edges,
) -> list:
    docs = []
    if not isinstance(edges, list):
        return docs
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        docs.append(
            {
                "node_id": node_id,
                "placement": placement,
                "environment": environment,
                "disabled": disabled,
                "relationship": edge.get("relationship"),
                "source_type": edge.get("source_type"),
                "source_title": edge.get("source_title"),
                "target_type": edge.get("target_type"),
                "target_title": edge.get("target_title"),
            }
        )
    return docs


def containing_class(containment_path) -> Optional[str]:
    classes = [
        step
        for step in (containment_path or [])
        if isinstance(step, str) and step != "" and "[" not in step
    ]
    return classes[-1] if classes else None


def build_event_documents(
    node_id: str,
    placement: Optional[dict],
    disabled: bool,
    received: datetime,
    report: dict,
    latest: bool,
) -> list:
    docs = []
    for resource in report.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        containment = resource.get("containment_path") or []
        for event in resource.get("events") or []:
            docs.append(
                {
                    "node_id": node_id,
                    "placement": placement,
                    "disabled": disabled,
                    "created": received,
                    "report_id": received,
                    "report_hash": report.get("hash"),
                    "latest": latest,
                    "run_start_time": report.get("start_time"),
                    "run_end_time": report.get("end_time"),
                    "environment": report.get("environment"),
                    "configuration_version": report.get("configuration_version"),
                    "status": event.get("status"),
                    "timestamp": event.get("timestamp"),
                    "resource_type": resource.get("resource_type"),
                    "resource_title": resource.get("resource_title"),
                    "property": event.get("property"),
                    "name": event.get("name"),
                    "new_value": event.get("new_value"),
                    "old_value": event.get("old_value"),
                    "message": event.get("message"),
                    "file": resource.get("file"),
                    "line": resource.get("line"),
                    "containment_path": containment,
                    "containing_class": containing_class(containment),
                    "corrective_change": event.get("corrective_change"),
                }
            )
    return docs


def catalog_payload(data: dict) -> dict:
    resources = normalise_resources(data.get("resources"))
    exported = [resource for resource in resources if resource.get("exported")]
    edges = normalise_edges(data.get("edges"))
    payload = {
        "catalog_uuid": data.get("catalog_uuid"),
        "num_resources": len(resources),
        "num_resources_exported": len(exported),
        "resources": resources,
        "resources_exported": exported,
        "edges": edges,
        "version": _as_string(data.get("version")),
        "transaction_uuid": data.get("transaction_uuid"),
        "code_id": data.get("code_id"),
        "job_id": _as_string(data.get("job_id")),
        "producer": data.get("producer"),
        "producer_timestamp": parse_wire_timestamp(data.get("producer_timestamp")),
    }
    payload["hash"] = stable_hash(
        {
            "certname": data.get("certname"),
            "version": payload["version"],
            "resources": [
                [resource.get("type"), resource.get("title")] for resource in resources
            ],
            "edges": edges,
        }
    )
    payload["content_hash"] = catalog_content_hash(resources, edges)
    return payload


def catalog_metadata(catalog: dict) -> dict:
    return {
        key: value
        for key, value in catalog.items()
        if key not in CATALOG_CONTENT_FIELDS
    }


def with_skipped_events(resources) -> list:
    if not isinstance(resources, list):
        return []
    prepared = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        item = dict(resource)
        events = item.get("events") or []
        if item.get("skipped") and not events:
            events = [
                {
                    "status": "skipped",
                    "timestamp": item.get("timestamp"),
                    "name": None,
                    "property": None,
                    "new_value": None,
                    "old_value": None,
                    "corrective_change": False,
                    "message": None,
                }
            ]
        item["events"] = events
        prepared.append(item)
    return prepared


def report_payload(data: dict) -> dict:
    payload = {
        "status": data.get("status"),
        "noop": data.get("noop"),
        "noop_pending": data.get("noop_pending"),
        "corrective_change": data.get("corrective_change"),
        "catalog_uuid": data.get("catalog_uuid"),
        "logs": data.get("logs") or [],
        "metrics": data.get("metrics") or [],
        "resources": with_skipped_events(data.get("resources")),
        "type": data.get("type") or "agent",
        "puppet_version": data.get("puppet_version"),
        "report_format": data.get("report_format"),
        "configuration_version": _as_string(data.get("configuration_version")),
        "start_time": parse_wire_timestamp(data.get("start_time")),
        "end_time": parse_wire_timestamp(data.get("end_time")),
        "producer_timestamp": parse_wire_timestamp(data.get("producer_timestamp")),
        "producer": data.get("producer"),
        "transaction_uuid": data.get("transaction_uuid"),
        "code_id": data.get("code_id"),
        "job_id": _as_string(data.get("job_id")),
        "cached_catalog_status": data.get("cached_catalog_status"),
        "environment": data.get("environment"),
        "latest": True,
    }
    payload["hash"] = stable_hash(
        {
            "certname": data.get("certname"),
            "transaction_uuid": payload["transaction_uuid"],
            "start_time": str(payload["start_time"]),
            "end_time": str(payload["end_time"]),
            "configuration_version": payload["configuration_version"],
        }
    )
    return payload


def _as_string(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


REPORT_DETAIL_FIELDS = ("logs", "resources")


def report_summary(report: dict) -> dict:
    return {
        key: value for key, value in report.items() if key not in REPORT_DETAIL_FIELDS
    }
