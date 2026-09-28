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


import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clj_reader import Kw  # noqa: E402
from clj_reader import Sym  # noqa: E402
from clj_reader import read_all  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")

BOOL_OPS = {"and", "or", "not"}
CMP_OPS = {"=", "~", "~>", ">", "<", ">=", "<=", "null?"}
QUERY_OPS = BOOL_OPS | CMP_OPS | {
    "in",
    "from",
    "extract",
    "subquery",
    "group_by",
    "function",
    "limit",
    "offset",
    "order_by",
    "array",
}
SELECT_RE = re.compile(r"^select_[a-z_]+$")
PQL_RE = re.compile(r"^\s*[a-z_]+(\s*\[|\s*\{)")

FILE_ENDPOINT = {
    "aggregate_event_counts_test": "/pdb/query/v4/aggregate-event-counts",
    "catalog_input_contents_test": "/pdb/query/v4/catalog-input-contents",
    "catalog_inputs_test": "/pdb/query/v4/catalog-inputs",
    "catalogs_test": "/pdb/query/v4/catalogs",
    "command_test": "/pdb/cmd/v1",
    "environments_test": "/pdb/query/v4/environments",
    "event_counts_test": "/pdb/query/v4/event-counts",
    "events_test": "/pdb/query/v4/events",
    "explore_test": "/pdb/query/v4",
    "facts_test": "/pdb/query/v4/facts",
    "index_test": "/pdb/query/v4",
    "inventory_test": "/pdb/query/v4/inventory",
    "nodes_test": "/pdb/query/v4/nodes",
    "packages_test": "/pdb/query/v4/packages",
    "paging_test": "/pdb/query/v4",
    "producers_test": "/pdb/query/v4/producers",
    "query_logging_test": "/pdb/query/v4",
    "query_test": "/pdb/query/v4",
    "reports_test": "/pdb/query/v4/reports",
    "resources_test": "/pdb/query/v4/resources",
}


def is_query_node(node):
    return (
        isinstance(node, list)
        and node
        and isinstance(node[0], str)
        and (node[0] in QUERY_OPS or SELECT_RE.match(node[0]))
    )


def has_symbols(node):
    if isinstance(node, (Sym, Kw)):
        return True
    if isinstance(node, list):
        return any(has_symbols(item) for item in node)
    if isinstance(node, dict):
        return any(has_symbols(value) for value in node.values())
    return False


def jsonable(node):
    if isinstance(node, Sym):
        return {"__sym__": node.name}
    if isinstance(node, Kw):
        return {"__kw__": node.name}
    if isinstance(node, list):
        return [jsonable(item) for item in node]
    if isinstance(node, dict):
        return {key: jsonable(value) for key, value in node.items()}
    return node


def field_name(field):
    if isinstance(field, str):
        return field
    if isinstance(field, list) and field and isinstance(field[0], str):
        if field[0] in ("parameter", "fact", "resource_metadata"):
            return f"[{field[0]} *]"
        return "[" + " ".join(x for x in field if isinstance(x, str)) + "]"
    return "<dynamic>"


def collect_features(node, feats):
    if not isinstance(node, list) or not node:
        return
    head = node[0]
    if isinstance(head, str):
        if head in QUERY_OPS or SELECT_RE.match(head):
            feats["operators"].add(head)
        if head in CMP_OPS and len(node) >= 2:
            feats["fields"].add(field_name(node[1]))
        if head == "in" and len(node) >= 2:
            field = node[1]
            if isinstance(field, list) and all(isinstance(f, str) for f in field):
                feats["fields"].update(field)
            else:
                feats["fields"].add(field_name(field))
            if len(node) >= 3 and isinstance(node[2], list) and node[2]:
                if node[2][0] == "extract":
                    feats["operators"].add("in+subquery")
        if head == "from" and len(node) >= 2 and isinstance(node[1], str):
            feats["entities"].add(node[1])
        if head == "extract" and len(node) >= 2:
            columns = node[1]
            if isinstance(columns, str):
                feats["fields"].add(columns)
            elif isinstance(columns, list):
                for column in columns:
                    if isinstance(column, str):
                        feats["fields"].add(column)
                    elif isinstance(column, list) and column and column[0] == "function":
                        feats["operators"].add("function")
                        if len(column) >= 2 and isinstance(column[1], str):
                            feats["functions"].add(column[1])
    for child in node:
        collect_features(child, feats)


def walk(node, out):
    if is_query_node(node):
        out.append(node)
        return
    if isinstance(node, list):
        for child in node:
            walk(child, out)
    elif isinstance(node, dict):
        for value in node.values():
            walk(value, out)


def extract_pql(text):
    out = []
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', text):
        candidate = match.group(1)
        if "{" in candidate and "}" in candidate and PQL_RE.match(candidate):
            out.append(candidate.replace('\\"', '"'))
    return sorted(set(out))


def extract_clj(root):
    http_dir = os.path.join(root, "test", "puppetlabs", "puppetdb", "http")
    corpus = []
    features = {}
    for name in sorted(os.listdir(http_dir)):
        if not name.endswith(".clj"):
            continue
        stem = name[:-4]
        endpoint = FILE_ENDPOINT.get(stem, "/pdb/query/v4")
        with open(os.path.join(http_dir, name), encoding="utf-8") as handle:
            text = handle.read()
        found = []
        for chunk in re.split(r"\n(?=\s*\((?:deftest|testing)\b)", text):
            expects_error = "HTTP_BAD_REQUEST" in chunk or "http-error" in chunk
            sub = []
            walk(read_all(chunk), sub)
            found.extend((query, expects_error) for query in sub)

        feats = {
            "operators": set(),
            "fields": set(),
            "entities": set(),
            "functions": set(),
        }
        seen = set()
        for query, expects_error in found:
            collect_features(query, feats)
            if has_symbols(query):
                continue
            key = json.dumps(jsonable(query), sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            corpus.append(
                {
                    "source": f"test/puppetlabs/puppetdb/http/{name}",
                    "path": endpoint,
                    "method": "GET",
                    "query": json.loads(key),
                    "expects_error": expects_error,
                }
            )
        for pql in extract_pql(text):
            corpus.append(
                {
                    "source": f"test/puppetlabs/puppetdb/http/{name}",
                    "path": endpoint,
                    "method": "GET",
                    "pql": pql,
                }
            )
        features[endpoint] = {
            key: sorted(value | set(features.get(endpoint, {}).get(key, [])))
            for key, value in feats.items()
        }
    return corpus, features


def extract_locust(root):
    locust_dir = os.path.join(root, "locust", "load-test")
    out = []
    for name in sorted(os.listdir(locust_dir)):
        if not name.endswith(".yaml"):
            continue
        with open(os.path.join(locust_dir, name)) as handle:
            entries = yaml.safe_load(handle) or []
        for entry in entries:
            out.append(
                {
                    "source": f"locust/load-test/{name}",
                    "consumer": name[:-5],
                    "path": entry.get("path"),
                    "method": (entry.get("method") or "GET").upper(),
                    "alias": entry.get("alias"),
                    "query": entry.get("query"),
                }
            )
    return out


def main():
    if len(sys.argv) != 2:
        print("usage: extract_upstream.py <path-to-openvoxdb-checkout>")
        return 1
    root = sys.argv[1]
    os.makedirs(CORPUS, exist_ok=True)

    clj, features = extract_clj(root)
    locust = extract_locust(root)

    with open(os.path.join(CORPUS, "openvoxdb_queries.json"), "w") as handle:
        json.dump(clj, handle, indent=1)
    with open(os.path.join(CORPUS, "locust_queries.json"), "w") as handle:
        json.dump(locust, handle, indent=1)
    with open(os.path.join(CORPUS, "upstream_features.json"), "w") as handle:
        json.dump(features, handle, indent=1)

    print(f"openvoxdb_queries.json: {len(clj)} entries")
    print(f"locust_queries.json:    {len(locust)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
