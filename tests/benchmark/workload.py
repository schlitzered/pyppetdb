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

import random
import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta

OS_FAMILIES = ("Debian", "RedHat", "Suse", "FreeBSD")
ENVIRONMENTS = ("production", "staging", "development")
RESOURCE_TYPES = ("File", "Package", "Service", "Exec", "Notify", "User")
REPORT_STATUSES = ("changed", "unchanged", "failed")
EVENT_STATUSES = ("success", "failure", "noop")

FACTS_VERSION = 5
CATALOG_VERSION = 9
REPORT_VERSION = 8
DEACTIVATE_VERSION = 3


def certname(index: int) -> str:
    return f"bench{index:05d}.example.com"


def _rng(index: int, seed: int) -> random.Random:
    return random.Random(f"{seed}:{index}")


def _base_time() -> datetime:
    now = datetime.now(UTC)
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _timestamp(index: int) -> str:
    return _iso(_base_time() + timedelta(seconds=index % 600))


def facts_payload(index: int, seed: int, fact_count: int = 150, generation: int = 0) -> dict:
    rng = _rng(index, seed)
    family = OS_FAMILIES[index % len(OS_FAMILIES)]
    environment = ENVIRONMENTS[index % len(ENVIRONMENTS)]
    values = {
        "osfamily": family,
        "kernel": "Linux" if family != "FreeBSD" else "FreeBSD",
        "uptime_seconds": rng.randint(100, 10_000_000),
        "memorysize_mb": rng.choice([2048, 4096, 8192, 16384, 32768]),
        "processorcount": rng.choice([2, 4, 8, 16]),
        "virtual": rng.choice(["physical", "kvm", "vmware", "docker"]),
        "os": {
            "family": family,
            "name": family,
            "release": {"major": str(rng.randint(8, 15)), "minor": "0"},
            "distro": {"codename": rng.choice(["bookworm", "trixie", "noble"])},
        },
        "networking": {
            "fqdn": certname(index),
            "domain": "example.com",
            "ip": f"10.{index // 256 % 256}.{index % 256}.10",
            "interfaces": {
                "eth0": {"ip": f"10.0.{index % 256}.10", "mtu": 1500},
                "lo": {"ip": "127.0.0.1", "mtu": 65536},
            },
        },
        "trusted": {
            "certname": certname(index),
            "authenticated": "remote",
            "extensions": {"pp_role": rng.choice(["web", "db", "cache"])},
        },
        "role": rng.choice(["web", "db", "cache", "batch"]),
        "datacenter": rng.choice(["dc1", "dc2", "dc3"]),
        "bench_generation": str(generation),
    }
    for filler in range(max(0, fact_count - len(values))):
        values[f"custom_fact_{filler:03d}"] = rng.choice(
            [
                f"value-{rng.randint(0, 50)}",
                rng.randint(0, 10000),
                rng.random() < 0.5,
            ]
        )
    return {
        "certname": certname(index),
        "environment": environment,
        "producer_timestamp": _timestamp(index),
        "producer": f"master{index % 3}.example.com",
        "values": values,
    }


def catalog_payload(index: int, seed: int, resource_count: int = 200, generation: int = 0) -> dict:
    rng = _rng(index, seed)
    environment = ENVIRONMENTS[index % len(ENVIRONMENTS)]
    name = certname(index)

    resources = [
        {
            "type": "Stage",
            "title": "main",
            "exported": False,
            "file": None,
            "line": None,
            "tags": ["stage"],
            "parameters": {},
        },
        {
            "type": "Class",
            "title": "Settings",
            "exported": False,
            "file": None,
            "line": None,
            "tags": ["class", "settings"],
            "parameters": {},
        },
    ]
    edges = [
        {
            "source": {"type": "Stage", "title": "main"},
            "target": {"type": "Class", "title": "Settings"},
            "relationship": "contains",
        }
    ]

    for position in range(max(0, resource_count - len(resources))):
        resource_type = RESOURCE_TYPES[position % len(RESOURCE_TYPES)]
        title = f"/opt/bench/{resource_type.lower()}-{position:04d}"
        exported = position % 25 == 0
        resources.append(
            {
                "type": resource_type,
                "title": title,
                "exported": exported,
                "file": "/etc/puppetlabs/code/modules/bench/manifests/init.pp",
                "line": position + 1,
                "tags": [
                    resource_type.lower(),
                    "bench",
                    f"group{position % 5}",
                ],
                "parameters": {
                    "ensure": rng.choice(["present", "file", "running"]),
                    "owner": "root" if position % 3 else "nobody",
                    "group": "root",
                    "mode": "0644",
                    "content": f"managed by bench {position}",
                },
            }
        )
        edges.append(
            {
                "source": {"type": "Class", "title": "Settings"},
                "target": {"type": resource_type, "title": title},
                "relationship": "contains",
            }
        )

    return {
        "certname": name,
        "version": f"{generation}-{1710930000 + index}",
        "environment": environment,
        "transaction_uuid": str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"tx{seed}:{generation}:{index}")
        ),
        "catalog_uuid": str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"cat{seed}:{generation}:{index}")
        ),
        "code_id": None,
        "job_id": None,
        "producer_timestamp": _timestamp(index),
        "producer": f"master{index % 3}.example.com",
        "resources": resources,
        "edges": edges,
    }


def report_payload(index: int, seed: int, event_resources: int = 40, generation: int = 0) -> dict:
    rng = _rng(index, seed)
    environment = ENVIRONMENTS[index % len(ENVIRONMENTS)]
    status = REPORT_STATUSES[index % len(REPORT_STATUSES)]
    start = _base_time() + timedelta(seconds=index % 600)
    end = start + timedelta(seconds=rng.randint(5, 90))

    resources = []
    for position in range(event_resources):
        resource_type = RESOURCE_TYPES[position % len(RESOURCE_TYPES)]
        title = f"/opt/bench/{resource_type.lower()}-{position:04d}"
        skipped = position % 11 == 0
        event_status = EVENT_STATUSES[position % len(EVENT_STATUSES)]
        events = []
        if not skipped:
            events.append(
                {
                    "status": event_status,
                    "timestamp": _iso(start),
                    "name": None,
                    "property": "ensure",
                    "new_value": "present",
                    "old_value": "absent",
                    "corrective_change": position % 7 == 0,
                    "message": None if event_status == "success" else f"changed {title}",
                }
            )
        resources.append(
            {
                "timestamp": _iso(start),
                "resource_type": resource_type,
                "resource_title": title,
                "file": "/etc/puppetlabs/code/modules/bench/manifests/init.pp",
                "line": position + 1,
                "containment_path": ["Stage[main]", "Bench::Config", f"{resource_type}[{title}]"],
                "corrective_change": position % 7 == 0,
                "skipped": skipped,
                "events": events,
            }
        )

    return {
        "certname": certname(index),
        "environment": environment,
        "puppet_version": "8.4.0",
        "report_format": 12,
        "configuration_version": f"{generation}-{1710930000 + index}",
        "start_time": _iso(start),
        "end_time": _iso(end),
        "producer_timestamp": _timestamp(index),
        "producer": f"master{index % 3}.example.com",
        "transaction_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tx{seed}:{index}")),
        "catalog_uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cat{seed}:{index}")),
        "code_id": None,
        "job_id": None,
        "cached_catalog_status": "not_used",
        "noop": False,
        "noop_pending": False,
        "corrective_change": index % 7 == 0,
        "status": status,
        "metrics": [
            {"category": "time", "name": "total", "value": 12.5},
            {"category": "resources", "name": "total", "value": 200},
        ],
        "logs": [
            {
                "file": None,
                "line": None,
                "level": "notice",
                "message": f"Applied catalog for {certname(index)}",
                "source": "Puppet",
                "tags": ["notice"],
                "time": _iso(start),
            }
        ],
        "resources": resources,
    }


COMMANDS = (
    ("replace_facts", FACTS_VERSION, facts_payload),
    ("replace_catalog", CATALOG_VERSION, catalog_payload),
    ("store_report", REPORT_VERSION, report_payload),
)

WRITE_PROBES = {
    "replace_facts": {
        "entity": "facts",
        "query": lambda generation, since: [
            "and",
            ["=", "name", "bench_generation"],
            ["=", "value", str(generation)],
        ],
        "unit": "facts",
        "per_command": 150,
    },
    "replace_catalog": {
        "entity": "nodes",
        "query": lambda generation, since: [">=", "catalog_timestamp", since],
        "unit": "resources",
        "per_command": 200,
    },
    "store_report": {
        "entity": "reports",
        "query": lambda generation, since: [
            "~",
            "configuration_version",
            f"^{generation}-",
        ],
        "unit": "reports",
        "per_command": 1,
    },
}


def query(name: str, path: str, ast=None, params=None) -> dict:
    return {"name": name, "path": path, "ast": ast, "params": params or {}}


def build_queries(node_count: int) -> list:
    sample = certname(node_count // 2)
    return [
        query("nodes_all", "/pdb/query/v4/nodes"),
        query("nodes_by_certname", "/pdb/query/v4/nodes", ["=", "certname", sample]),
        query(
            "nodes_by_fact",
            "/pdb/query/v4/nodes",
            ["=", ["fact", "osfamily"], "Debian"],
        ),
        query(
            "nodes_active_count",
            "/pdb/query/v4",
            [
                "from",
                "nodes",
                ["extract", [["function", "count"]], ["=", "node_state", "active"]],
            ],
        ),
        query(
            "nodes_group_by_status",
            "/pdb/query/v4",
            [
                "from",
                "nodes",
                [
                    "extract",
                    [["function", "count"], "latest_report_status"],
                    ["group_by", "latest_report_status"],
                ],
            ],
        ),
        query("facts_by_name", "/pdb/query/v4/facts", ["=", "name", "osfamily"]),
        query("fact_names", "/pdb/query/v4/fact-names"),
        query(
            "inventory_dotted",
            "/pdb/query/v4/inventory",
            ["=", "facts.os.family", "Debian"],
        ),
        query("resources_by_type", "/pdb/query/v4/resources", ["=", "type", "File"]),
        query(
            "resources_by_type_title",
            "/pdb/query/v4/resources",
            [
                "and",
                ["=", "type", "File"],
                ["=", "title", "/opt/bench/file-0006"],
            ],
        ),
        query(
            "resources_by_parameter",
            "/pdb/query/v4/resources",
            [
                "and",
                ["=", "type", "Package"],
                ["=", ["parameter", "owner"], "nobody"],
            ],
        ),
        query(
            "resources_exported",
            "/pdb/query/v4/resources",
            ["=", "exported", True],
        ),
        query(
            "resources_exported_subquery",
            "/pdb/query/v4/resources",
            [
                "and",
                ["=", "exported", True],
                [
                    "in",
                    "certname",
                    [
                        "extract",
                        "certname",
                        [
                            "select_facts",
                            ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
                        ],
                    ],
                ],
            ],
        ),
        query(
            "catalogs_by_certname",
            "/pdb/query/v4/catalogs",
            ["=", "certname", sample],
        ),
        query("reports_by_certname", "/pdb/query/v4/reports", ["=", "certname", sample]),
        query(
            "reports_failed",
            "/pdb/query/v4/reports",
            ["=", "status", "failed"],
        ),
        query(
            "events_failed",
            "/pdb/query/v4/events",
            ["=", "status", "failure"],
        ),
        query(
            "event_counts_certname",
            "/pdb/query/v4/event-counts",
            ["=", "certname", sample],
            {"summarize_by": "certname"},
        ),
        query("environments", "/pdb/query/v4/environments"),
        query(
            "nodes_paged",
            "/pdb/query/v4/nodes",
            None,
            {
                "limit": "25",
                "offset": "0",
                "include_total": "true",
                "order_by": '[{"field":"certname","order":"asc"}]',
            },
        ),
    ]
