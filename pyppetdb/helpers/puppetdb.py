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

import hashlib
import json
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
                    "corrective_change": None,
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
