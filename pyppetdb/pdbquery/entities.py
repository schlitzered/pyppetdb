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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import PrivateAttr

FACT_FIELD_FORMS = ("fact", "parameter")


class _Unset:
    def __repr__(self):
        return "<unset>"


_UNSET = _Unset()


class Column(BaseModel):
    name: str
    type: str = "string"
    expr: Any = None
    projected: bool = True
    queryable: bool = True
    dotted: bool = False
    virtual: Optional[Dict[str, str]] = None
    prefilter: Optional[str] = None
    prefilter_kind: str = "path"
    prefilter_default: Any = _UNSET

    def __init__(self, name: str, type: str = "string", expr: Any = None, **kwargs):
        super().__init__(name=name, type=type, expr=expr, **kwargs)


class Entity(BaseModel):
    name: str
    collection: str
    columns: List[Column]
    stages: List[Any] = Field(default_factory=list)
    relations: Dict[str, Any] = Field(default_factory=dict)
    field_forms: Dict[str, str] = Field(default_factory=dict)
    field_aliases: Dict[str, str] = Field(default_factory=dict)
    python_expand: Optional[str] = None
    scalar_result: Optional[str] = None
    element_filter: Optional[Dict[str, Any]] = None
    cacheable: bool = False
    distinct_rows: bool = False

    _by_name: Dict[str, Column] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context) -> None:
        self._by_name = {column.name: column for column in self.columns}

    @property
    def by_name(self) -> dict:
        return self._by_name

    @property
    def document_rows(self) -> bool:
        if self.element_filter or self.python_expand:
            return False
        return all(
            isinstance(stage, dict) and set(stage) == {"$match"}
            for stage in self.stages
        )

    def queryable_names(self) -> list:
        return [column.name for column in self.columns if column.queryable]

    def projected_names(self) -> list:
        return [column.name for column in self.columns if column.projected]

    def resolve(self, field):
        if isinstance(field, list):
            if len(field) != 2 or not isinstance(field[0], str):
                return None, None
            alias = self.field_aliases.get(" ".join(str(item) for item in field))
            if alias is not None:
                return self._by_name[alias], alias
            form = self.field_forms.get(field[0])
            if form is None or not isinstance(field[1], str):
                return None, None
            column = self._by_name.get(form)
            if column is None:
                return None, None
            return column, f"{form}.{field[1]}"
        if not isinstance(field, str):
            return None, None
        column = self._by_name.get(field)
        if column is not None and column.queryable:
            return column, field
        if "." in field:
            head = field.split(".", 1)[0]
            parent = self._by_name.get(head)
            if parent is not None and parent.queryable and parent.dotted:
                return parent, field
        return None, None

    def element_path(self, column_name: str) -> Optional[str]:
        spec = self.element_filter
        if not spec:
            return None
        paths = spec.get("paths")
        if paths is not None:
            return paths.get(column_name)
        column = self._by_name.get(column_name)
        prefix = spec.get("prefix")
        if column is None or not prefix or not column.prefilter:
            return None
        if not column.prefilter.startswith(prefix):
            return None
        return column.prefilter[len(prefix):]

    def build_stages(self, element_cond=None, pinned_keys=None) -> list:
        spec = self.element_filter
        if not spec:
            return list(self.stages)
        if spec.get("nested"):
            return self._nested_stages(spec, element_cond)
        field = spec["field"]
        source = spec.get("input") or f"${spec['array']}"
        if pinned_keys and spec.get("key_path"):
            source = self._pinned_source(spec, pinned_keys)
            element_cond = None
        if element_cond is not None:
            source = {
                "$filter": {
                    "input": source,
                    "as": "item",
                    "cond": element_cond,
                }
            }
        projection = {key: 1 for key in spec["keep"]}
        projection[field] = source
        stages = [{"$match": spec["guard"]}] if spec.get("guard") else []
        if spec.get("array"):
            stages = [{"$match": {spec["array"]: {"$type": "array"}}}]
        stages.append({"$project": projection})
        stages.append({"$unwind": f"${field}"})
        stages.extend(spec.get("tail", ()))
        return stages

    @staticmethod
    def _pinned_source(spec, pinned_keys) -> dict:
        path = spec["key_path"]
        entries = [
            {spec["key_name"]: key, spec["key_value"]: f"${path}.{key}"}
            for key in sorted(pinned_keys)
        ]
        return {
            "$filter": {
                "input": entries,
                "as": "item",
                "cond": {
                    "$ne": [{"$type": f"$$item.{spec['key_value']}"}, "missing"]
                },
            }
        }

    @staticmethod
    def _nested_stages(spec, element_cond) -> list:
        array = spec["array"]
        nested = spec["nested"]
        stages = [{"$match": {array: {"$type": "array"}}}]
        if element_cond:
            outer = element_cond.get("outer")
            inner = element_cond.get("inner")
            kept = {"$ifNull": [f"${array}", []]}
            if outer is not None:
                kept = {"$filter": {"input": kept, "as": "item", "cond": outer}}
            if inner is None:
                replacement = kept
            else:
                filtered = {
                    "$filter": {
                        "input": {"$ifNull": [f"$$item.{nested}", []]},
                        "as": "nested",
                        "cond": inner,
                    }
                }
                replacement = {
                    "$map": {
                        "input": kept,
                        "as": "item",
                        "in": {"$mergeObjects": ["$$item", {nested: filtered}]},
                    }
                }
            stages.append({"$addFields": {array: replacement}})
        stages.append({"$unwind": f"${array}"})
        stages.append({"$match": {f"{array}.{nested}": {"$type": "array"}}})
        stages.append({"$unwind": f"${array}.{nested}"})
        return stages


def _child(data, href_parts):
    return {"data": data, "href": {"$concat": href_parts}}


def _containing_class(path_expr):
    return {
        "$let": {
            "vars": {
                "classes": {
                    "$filter": {
                        "input": {"$ifNull": [path_expr, []]},
                        "as": "step",
                        "cond": {
                            "$and": [
                                {"$ne": ["$$step", ""]},
                                {"$eq": [{"$indexOfBytes": ["$$step", "["]}, -1]},
                            ]
                        },
                    }
                }
            },
            "in": {"$ifNull": [{"$arrayElemAt": ["$$classes", -1]}, None]},
        }
    }


def _node_state():
    return {"$cond": [{"$eq": ["$disabled", True]}, "inactive", "active"]}


def _deactivated():
    return {"$cond": [{"$eq": ["$disabled", True]}, "$change_last", None]}


NODES = Entity(
    name="nodes",
    collection="nodes",
    field_forms={"fact": "facts"},
    field_aliases={"node active": "node_state"},
    columns=[
        Column("certname", "string", "$id"),
        Column("deactivated", "timestamp", _deactivated()),
        Column("expired", "timestamp", {"$literal": None}),
        Column("catalog_timestamp", "timestamp", "$change_catalog"),
        Column("facts_timestamp", "timestamp", "$change_facts"),
        Column("report_timestamp", "timestamp", "$report.end_time"),
        Column("catalog_environment", "string", "$environment"),
        Column("facts_environment", "string", "$environment"),
        Column("report_environment", "string", "$environment"),
        Column("latest_report_hash", "string", "$report.hash"),
        Column("latest_report_status", "string", "$report.status"),
        Column("latest_report_noop", "boolean", "$report.noop"),
        Column("latest_report_noop_pending", "boolean", "$report.noop_pending"),
        Column(
            "latest_report_corrective_change",
            "boolean",
            "$report.corrective_change",
        ),
        Column("latest_report_job_id", "string", "$report.job_id"),
        Column("cached_catalog_status", "string", "$report.cached_catalog_status"),
        Column("node_state", "state", _node_state(), projected=False),
        Column("facts", "json", "$facts", projected=False, dotted=True),
    ],
)

FACT_ELEMENT_FILTER = {
    "guard": {"facts": {"$type": "object"}},
    "input": {"$objectToArray": "$facts"},
    "field": "kv",
    "paths": {"name": "k", "value": "v"},
    "key_path": "facts",
    "key_name": "k",
    "key_value": "v",
    "keep": (
        "id",
        "environment",
        "disabled",
        "producer",
        "producer_timestamp",
        "change_facts",
    ),
}

FACTS = Entity(
    name="facts",
    collection="nodes",
    element_filter=FACT_ELEMENT_FILTER,
    columns=[
        Column("certname", "string", "$id"),
        Column("name", "string", "$kv.k"),
        Column("value", "json", "$kv.v", dotted=True),
        Column("environment", "string", "$environment"),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

FACT_NAMES = Entity(
    name="fact-names",
    collection="nodes",
    element_filter={
        **FACT_ELEMENT_FILTER,
        "tail": ({"$group": {"_id": "$kv.k"}}, {"$sort": {"_id": 1}}),
    },
    scalar_result="name",
    cacheable=True,
    columns=[Column("name", "string", "$_id")],
)

FACTSETS = Entity(
    name="factsets",
    collection="nodes",
    columns=[
        Column("certname", "string", "$id"),
        Column("environment", "string", "$environment"),
        Column("timestamp", "timestamp", "$change_facts"),
        Column("producer_timestamp", "timestamp", "$producer_timestamp"),
        Column("producer", "string", "$producer"),
        Column("hash", "string", "$facts_hash"),
        Column(
            "facts",
            "json",
            _child(
                {
                    "$map": {
                        "input": {"$objectToArray": "$facts"},
                        "as": "entry",
                        "in": {"name": "$$entry.k", "value": "$$entry.v"},
                    }
                },
                ["/pdb/query/v4/factsets/", "$id", "/facts"],
            ),
        ),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

INVENTORY = Entity(
    name="inventory",
    collection="nodes",
    columns=[
        Column("certname", "string", "$id"),
        Column("timestamp", "timestamp", "$change_facts"),
        Column("environment", "string", "$environment"),
        Column("facts", "json", "$facts", dotted=True),
        Column("trusted", "json", "$facts.trusted", dotted=True),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

FACT_CONTENTS = Entity(
    name="fact-contents",
    collection="nodes",
    python_expand="fact_contents",
    columns=[
        Column("certname", "string", None),
        Column("environment", "string", None),
        Column("name", "string", None),
        Column("path", "path", None),
        Column("value", "json", None),
        Column("node_state", "string", None, projected=False),
    ],
)

FACT_PATHS = Entity(
    name="fact-paths",
    collection="nodes",
    python_expand="fact_paths",
    distinct_rows=True,
    cacheable=True,
    columns=[
        Column("name", "string", None),
        Column("path", "path", None),
        Column("type", "string", None),
    ],
)

RESOURCES = Entity(
    name="resources",
    collection="nodes",
    field_forms={"parameter": "parameters"},
    element_filter={
        "array": "catalog.resources",
        "field": "resource",
        "prefix": "catalog.resources.",
        "keep": ("id", "environment", "disabled"),
    },
    columns=[
        Column("certname", "string", "$id"),
        Column("environment", "string", "$environment"),
        Column("resource", "string", "$resource.resource"),
        Column("type", "string", "$resource.type"),
        Column("title", "string", "$resource.title"),
        Column("exported", "boolean", {"$ifNull": ["$resource.exported", False]}),
        Column("tags", "array", {"$ifNull": ["$resource.tags", []]}),
        Column("file", "string", "$resource.file"),
        Column("line", "integer", "$resource.line"),
        Column(
            "parameters",
            "json",
            {"$ifNull": ["$resource.parameters", {}]},
            dotted=True,
        ),
        Column("node_state", "state", _node_state(), projected=False),
        Column("tag", "string", {"$ifNull": ["$resource.tags", []]}, projected=False),
    ],
)

EDGES = Entity(
    name="edges",
    collection="nodes",
    element_filter={
        "array": "catalog.edges",
        "field": "edge",
        "prefix": "catalog.edges.",
        "keep": ("id", "environment", "disabled"),
    },
    columns=[
        Column("certname", "string", "$id"),
        Column("relationship", "string", "$edge.relationship"),
        Column("source_type", "string", "$edge.source_type"),
        Column("source_title", "string", "$edge.source_title"),
        Column("target_type", "string", "$edge.target_type"),
        Column("target_title", "string", "$edge.target_title"),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

CATALOGS = Entity(
    name="catalogs",
    collection="nodes",
    stages=[{"$match": {"catalog": {"$type": "object"}}}],
    columns=[
        Column("certname", "string", "$id"),
        Column("version", "string", "$catalog.version"),
        Column("environment", "string", "$environment"),
        Column("hash", "string", "$catalog.hash"),
        Column("transaction_uuid", "string", "$catalog.transaction_uuid"),
        Column("catalog_uuid", "string", "$catalog.catalog_uuid"),
        Column("code_id", "string", "$catalog.code_id"),
        Column("job_id", "string", "$catalog.job_id"),
        Column("producer", "string", "$catalog.producer"),
        Column(
            "producer_timestamp",
            "timestamp",
            "$catalog.producer_timestamp",
        ),
        Column(
            "edges",
            "json",
            _child(
                {"$ifNull": ["$catalog.edges", []]},
                ["/pdb/query/v4/catalogs/", "$id", "/edges"],
            ),
        ),
        Column(
            "resources",
            "json",
            _child(
                {"$ifNull": ["$catalog.resources", []]},
                ["/pdb/query/v4/catalogs/", "$id", "/resources"],
            ),
        ),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

CATALOG_INPUTS = Entity(
    name="catalog-inputs",
    collection="nodes",
    stages=[{"$match": {"catalog_inputs": {"$type": "object"}}}],
    columns=[
        Column("certname", "string", "$id"),
        Column("catalog_uuid", "string", "$catalog_inputs.catalog_uuid"),
        Column(
            "producer_timestamp",
            "timestamp",
            "$catalog_inputs.producer_timestamp",
        ),
        Column("inputs", "json", {"$ifNull": ["$catalog_inputs.inputs", []]}),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

CATALOG_INPUT_CONTENTS = Entity(
    name="catalog-input-contents",
    collection="nodes",
    stages=[
        {"$match": {"catalog_inputs.inputs": {"$type": "array"}}},
        {
            "$project": {
                "id": 1,
                "disabled": 1,
                "catalog_inputs": 1,
                "input": "$catalog_inputs.inputs",
            }
        },
        {"$unwind": "$input"},
    ],
    columns=[
        Column("certname", "string", "$id"),
        Column("catalog_uuid", "string", "$catalog_inputs.catalog_uuid"),
        Column(
            "producer_timestamp",
            "timestamp",
            "$catalog_inputs.producer_timestamp",
        ),
        Column("type", "string", {"$arrayElemAt": ["$input", 0]}),
        Column("name", "string", {"$arrayElemAt": ["$input", 1]}),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

PACKAGES = Entity(
    name="packages",
    collection="nodes",
    stages=[
        {"$match": {"package_inventory": {"$type": "array"}}},
        {
            "$project": {
                "id": 1,
                "disabled": 1,
                "package": "$package_inventory",
            }
        },
        {"$unwind": "$package"},
    ],
    columns=[
        Column("certname", "string", "$id"),
        Column("package_name", "string", {"$arrayElemAt": ["$package", 0]}),
        Column("version", "string", {"$arrayElemAt": ["$package", 1]}),
        Column("provider", "string", {"$arrayElemAt": ["$package", 2]}),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

RESOURCE_EVENTS_EXPR = {
    "data": {"$literal": None},
    "href": {
        "$concat": [
            "/pdb/query/v4/reports/",
            {"$ifNull": ["$report.hash", ""]},
            "/events",
        ]
    },
}


REPORTS = Entity(
    name="reports",
    collection="nodes_reports",
    columns=[
        Column("certname", "string", "$node_id"),
        Column("hash", "string", "$report.hash"),
        Column("puppet_version", "string", "$report.puppet_version"),
        Column("report_format", "integer", "$report.report_format"),
        Column(
            "configuration_version",
            "string",
            "$report.configuration_version",
        ),
        Column("start_time", "timestamp", "$report.start_time"),
        Column("end_time", "timestamp", "$report.end_time"),
        Column("receive_time", "timestamp", "$id"),
        Column("producer_timestamp", "timestamp", "$report.producer_timestamp"),
        Column("producer", "string", "$report.producer"),
        Column("transaction_uuid", "string", "$report.transaction_uuid"),
        Column("catalog_uuid", "string", "$report.catalog_uuid"),
        Column("code_id", "string", "$report.code_id"),
        Column("job_id", "string", "$report.job_id"),
        Column(
            "cached_catalog_status",
            "string",
            "$report.cached_catalog_status",
        ),
        Column("status", "string", "$report.status"),
        Column("noop", "boolean", "$report.noop"),
        Column("noop_pending", "boolean", "$report.noop_pending"),
        Column("corrective_change", "boolean", "$report.corrective_change"),
        Column("environment", "string", "$report.environment"),
        Column("type", "string", {"$ifNull": ["$report.type", "agent"]}),
        Column(
            "logs",
            "json",
            _child(
                {"$ifNull": ["$report.logs", []]},
                ["/pdb/query/v4/reports/", {"$ifNull": ["$report.hash", ""]}, "/logs"],
            ),
        ),
        Column(
            "metrics",
            "json",
            _child(
                {"$ifNull": ["$report.metrics", []]},
                [
                    "/pdb/query/v4/reports/",
                    {"$ifNull": ["$report.hash", ""]},
                    "/metrics",
                ],
            ),
        ),
        Column("resource_events", "json", RESOURCE_EVENTS_EXPR),
        Column("latest_report?", "boolean", "$report.latest", projected=False),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

EVENTS = Entity(
    name="events",
    collection="nodes_reports",
    element_filter={
        "array": "report.resources",
        "nested": "events",
        "prefix": "report.resources.",
        "nested_prefix": "report.resources.events.",
    },
    columns=[
        Column("certname", "string", "$node_id"),
        Column("report", "string", "$report.hash"),
        Column("run_start_time", "timestamp", "$report.start_time"),
        Column("run_end_time", "timestamp", "$report.end_time"),
        Column("report_receive_time", "timestamp", "$id"),
        Column("environment", "string", "$report.environment"),
        Column("status", "string", "$report.resources.events.status"),
        Column("timestamp", "timestamp", "$report.resources.events.timestamp"),
        Column("resource_type", "string", "$report.resources.resource_type"),
        Column("resource_title", "string", "$report.resources.resource_title"),
        Column("property", "string", "$report.resources.events.property"),
        Column("name", "string", "$report.resources.events.name"),
        Column("new_value", "json", "$report.resources.events.new_value"),
        Column("old_value", "json", "$report.resources.events.old_value"),
        Column("message", "string", "$report.resources.events.message"),
        Column("file", "string", "$report.resources.file"),
        Column("line", "integer", "$report.resources.line"),
        Column(
            "containment_path",
            "array",
            {"$ifNull": ["$report.resources.containment_path", []]},
        ),
        Column(
            "containing_class",
            "string",
            _containing_class("$report.resources.containment_path"),
        ),
        Column(
            "configuration_version",
            "string",
            "$report.configuration_version",
        ),
        Column(
            "corrective_change",
            "boolean",
            "$report.resources.events.corrective_change",
        ),
        Column("latest_report?", "boolean", "$report.latest", projected=False),
        Column("node_state", "state", _node_state(), projected=False),
    ],
)

ENVIRONMENTS = Entity(
    name="environments",
    collection="nodes",
    stages=[
        {"$match": {"environment": {"$type": "string"}}},
        {"$group": {"_id": "$environment"}},
    ],
    cacheable=True,
    columns=[Column("name", "string", "$_id")],
)

PRODUCERS = Entity(
    name="producers",
    collection="nodes",
    stages=[
        {"$match": {"producer": {"$type": "string"}}},
        {"$group": {"_id": "$producer"}},
    ],
    cacheable=True,
    columns=[Column("name", "string", "$_id")],
)

ENTITIES = {
    entity.name: entity
    for entity in (
        NODES,
        FACTS,
        FACT_NAMES,
        FACT_PATHS,
        FACT_CONTENTS,
        FACTSETS,
        INVENTORY,
        RESOURCES,
        EDGES,
        CATALOGS,
        CATALOG_INPUTS,
        CATALOG_INPUT_CONTENTS,
        PACKAGES,
        REPORTS,
        EVENTS,
        ENVIRONMENTS,
        PRODUCERS,
    )
}

ENTITY_ALIASES = {
    "package_inventory": "packages",
    "aggregate_event_counts": "events",
    "event_counts": "events",
}

EXPLICIT_RELATIONS = {
    ("reports", "events"): ("hash", "report"),
    ("events", "reports"): ("report", "hash"),
}


def _build_relations() -> None:
    for name, entity in ENTITIES.items():
        for other_name, other in ENTITIES.items():
            explicit = EXPLICIT_RELATIONS.get((name, other_name))
            if explicit is not None:
                entity.relations[other_name] = explicit
                continue
            local = _join_column(entity, other)
            if local is not None:
                entity.relations[other_name] = local


def _join_column(entity: Entity, other: Entity):
    if entity.name == "environments":
        return ("name", "environment") if "environment" in other.by_name else None
    if other.name == "environments":
        return ("environment", "name") if "environment" in entity.by_name else None
    if entity.name == "producers":
        return ("name", "producer") if "producer" in other.by_name else None
    if other.name == "producers":
        return ("producer", "name") if "producer" in entity.by_name else None
    for column in ("certname", "environment"):
        if column in entity.by_name and column in other.by_name:
            return (column, column)
    return None


_build_relations()


PREFILTERS = {
    "nodes": {
        "certname": "id",
        "catalog_environment": "environment",
        "facts_environment": "environment",
        "report_environment": "environment",
        "catalog_timestamp": "change_catalog",
        "facts_timestamp": "change_facts",
        "report_timestamp": "report.end_time",
        "latest_report_hash": "report.hash",
        "latest_report_status": "report.status",
        "latest_report_noop": "report.noop",
        "latest_report_noop_pending": "report.noop_pending",
        "latest_report_corrective_change": "report.corrective_change",
        "latest_report_job_id": "report.job_id",
        "cached_catalog_status": "report.cached_catalog_status",
        "facts": "facts",
        "node_state": ("disabled", "node_state"),
    },
    "facts": {
        "certname": "id",
        "environment": "environment",
        "name": ("facts", "fact_key"),
        "node_state": ("disabled", "node_state"),
    },
    "fact-names": {
        "name": ("facts", "fact_key"),
    },
    "fact-contents": {
        "certname": "id",
        "environment": "environment",
        "name": ("facts", "fact_key"),
        "node_state": ("disabled", "node_state"),
    },
    "fact-paths": {
        "name": ("facts", "fact_key"),
    },
    "factsets": {
        "certname": "id",
        "environment": "environment",
        "timestamp": "change_facts",
        "producer": "producer",
        "producer_timestamp": "producer_timestamp",
        "hash": "facts_hash",
        "node_state": ("disabled", "node_state"),
    },
    "inventory": {
        "certname": "id",
        "environment": "environment",
        "timestamp": "change_facts",
        "facts": "facts",
        "trusted": "facts.trusted",
        "node_state": ("disabled", "node_state"),
    },
    "resources": {
        "certname": "id",
        "environment": "environment",
        "resource": "catalog.resources.resource",
        "type": "catalog.resources.type",
        "title": "catalog.resources.title",
        "file": "catalog.resources.file",
        "line": "catalog.resources.line",
        "exported": ("catalog.resources.exported", "path", False),
        "tags": ("catalog.resources.tags", "path", []),
        "tag": ("catalog.resources.tags", "path", []),
        "parameters": ("catalog.resources.parameters", "path", {}),
        "node_state": ("disabled", "node_state"),
    },
    "edges": {
        "certname": "id",
        "relationship": "catalog.edges.relationship",
        "source_type": "catalog.edges.source_type",
        "source_title": "catalog.edges.source_title",
        "target_type": "catalog.edges.target_type",
        "target_title": "catalog.edges.target_title",
        "node_state": ("disabled", "node_state"),
    },
    "catalogs": {
        "certname": "id",
        "environment": "environment",
        "version": "catalog.version",
        "hash": "catalog.hash",
        "transaction_uuid": "catalog.transaction_uuid",
        "catalog_uuid": "catalog.catalog_uuid",
        "code_id": "catalog.code_id",
        "job_id": "catalog.job_id",
        "producer": "catalog.producer",
        "producer_timestamp": "catalog.producer_timestamp",
        "node_state": ("disabled", "node_state"),
    },
    "catalog-inputs": {
        "certname": "id",
        "catalog_uuid": "catalog_inputs.catalog_uuid",
        "producer_timestamp": "catalog_inputs.producer_timestamp",
        "node_state": ("disabled", "node_state"),
    },
    "catalog-input-contents": {
        "certname": "id",
        "catalog_uuid": "catalog_inputs.catalog_uuid",
        "producer_timestamp": "catalog_inputs.producer_timestamp",
        "node_state": ("disabled", "node_state"),
    },
    "packages": {
        "certname": "id",
        "node_state": ("disabled", "node_state"),
    },
    "reports": {
        "node_state": ("disabled", "node_state"),
        "certname": "node_id",
        "hash": "report.hash",
        "status": "report.status",
        "noop": "report.noop",
        "noop_pending": "report.noop_pending",
        "corrective_change": "report.corrective_change",
        "environment": "report.environment",
        "puppet_version": "report.puppet_version",
        "report_format": "report.report_format",
        "configuration_version": "report.configuration_version",
        "start_time": "report.start_time",
        "end_time": "report.end_time",
        "receive_time": "id",
        "producer": "report.producer",
        "producer_timestamp": "report.producer_timestamp",
        "transaction_uuid": "report.transaction_uuid",
        "catalog_uuid": "report.catalog_uuid",
        "code_id": "report.code_id",
        "job_id": "report.job_id",
        "cached_catalog_status": "report.cached_catalog_status",
        "latest_report?": "report.latest",
    },
    "events": {
        "node_state": ("disabled", "node_state"),
        "certname": "node_id",
        "report": "report.hash",
        "environment": "report.environment",
        "run_start_time": "report.start_time",
        "run_end_time": "report.end_time",
        "report_receive_time": "id",
        "status": "report.resources.events.status",
        "timestamp": "report.resources.events.timestamp",
        "property": "report.resources.events.property",
        "name": "report.resources.events.name",
        "new_value": "report.resources.events.new_value",
        "old_value": "report.resources.events.old_value",
        "message": "report.resources.events.message",
        "resource_type": "report.resources.resource_type",
        "resource_title": "report.resources.resource_title",
        "file": "report.resources.file",
        "line": "report.resources.line",
        "latest_report?": "report.latest",
    },
    "environments": {
        "name": "environment",
    },
    "producers": {
        "name": "producer",
    },
}


def _apply_prefilters() -> None:
    for entity_name, columns in PREFILTERS.items():
        entity = ENTITIES[entity_name]
        for column_name, spec in columns.items():
            column = entity.by_name.get(column_name)
            if column is None:
                raise KeyError(f"{entity_name} has no column {column_name}")
            if isinstance(spec, tuple):
                column.prefilter = spec[0]
                column.prefilter_kind = spec[1] if len(spec) > 1 else "path"
                if len(spec) > 2:
                    column.prefilter_default = spec[2]
            else:
                column.prefilter = spec


_apply_prefilters()


def get_entity(name: str):
    resolved = ENTITY_ALIASES.get(name, name)
    entity = ENTITIES.get(resolved)
    if entity is None:
        entity = ENTITIES.get(resolved.replace("_", "-"))
    return entity
