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

import argparse
import asyncio
import json
import os
import re
import ssl
import sys
from collections import Counter

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_cases import CASES  # noqa: E402
from diff_cases import GROUPS  # noqa: E402

TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)

HASH_FIELDS = {
    "hash",
    "latest_report_hash",
    "resource",
    "report",
    "logs.href",
    "metrics.href",
    "resource_events.href",
}
SET_FIELDS = {"tags"}
UNORDERED_CHILD_FIELDS = {
    "edges",
    "resources",
    "resources_exported",
    "resource_events",
    "inputs",
    "facts",
}
PE_ONLY_FIELDS = {"corrective_change", "latest_report_corrective_change"}
INGEST_FIELDS = {
    "receive_time",
    "report_receive_time",
    "catalog_timestamp",
    "facts_timestamp",
    "report_timestamp",
    "timestamp",
}

IGNORED_FIELDS = HASH_FIELDS | INGEST_FIELDS | PE_ONLY_FIELDS


ORDER_KEYS = {
    "nodes": ["certname"],
    "factsets": ["certname"],
    "inventory": ["certname"],
    "catalogs": ["certname"],
    "facts": ["certname", "name"],
    "fact-contents": ["certname", "name", "path"],
    "fact-paths": ["name", "path"],
    "resources": ["certname", "type", "title"],
    "edges": [
        "certname",
        "source_type",
        "source_title",
        "target_type",
        "target_title",
        "relationship",
    ],
    "reports": ["certname", "transaction_uuid"],
    "events": [
        "certname",
        "timestamp",
        "resource_type",
        "resource_title",
        "property",
        "name",
    ],
}
LIST_SUBROUTES = {"facts", "resources"}
UNPAGEABLE_TOKENS = ("extract", "function", "group_by", "limit", "offset", "order_by")
TOTAL_ROWS = "<total rows>"


def _entity_of(path: str, query):
    if isinstance(query, list) and len(query) > 1 and query[0] == "from":
        return query[1] if isinstance(query[1], str) else None
    tail = path.split("/pdb/query/v4", 1)[1] if "/pdb/query/v4" in path else ""
    parts = [part for part in tail.split("/") if part]
    if not parts:
        return None
    if parts[-1] in ORDER_KEYS:
        return parts[-1]
    if parts[0] in LIST_SUBROUTES:
        return parts[0]
    return None


def _shaped_at_top_level(query) -> bool:
    if not isinstance(query, list) or not query:
        return False
    if query[0] == "from":
        return any(
            isinstance(clause, list) and clause and clause[0] in UNPAGEABLE_TOKENS
            for clause in query[2:]
        )
    return query[0] in UNPAGEABLE_TOKENS


def _pageable(path: str, query, params: dict):
    if any(
        key in params
        for key in ("limit", "offset", "order_by", "summarize_by", "count_by")
    ):
        return None
    if _shaped_at_top_level(query):
        return None
    entity = _entity_of(path, query)
    return entity if entity in ORDER_KEYS else None


def _ignored(field: str) -> bool:
    return field in IGNORED_FIELDS or field.split(".")[0] in IGNORED_FIELDS


def _substitute(text: str, substitutions: dict) -> str:
    for placeholder, value in substitutions.items():
        text = text.replace(placeholder, value)
    return text


def normalise(value):
    if isinstance(value, dict):
        return {key: normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [normalise(item) for item in value]
    if isinstance(value, str) and TIMESTAMP.match(value):
        return _canonical_timestamp(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical_timestamp(value: str) -> str:
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1]
    text = re.sub(r"[+-]\d{2}:?\d{2}$", "", text)
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000000")[:6].rstrip("0")
        text = head + ("." + frac if frac else "")
    return text + "Z"


def _is_child(value) -> bool:
    return isinstance(value, dict) and set(value) == {"data", "href"}


def _stable(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _canonical_element(element):
    if not isinstance(element, dict):
        return element
    canonical = {}
    for key, value in element.items():
        if _ignored(key):
            continue
        if key in SET_FIELDS and isinstance(value, list):
            value = sorted(map(str, value))
        canonical[key] = value
    return canonical


def row_key(row, common=None):
    if not isinstance(row, dict):
        return json.dumps(normalise(row), sort_keys=True)
    parts = []
    for field in ("certname", "name", "title", "path", "resource_type",
                  "resource_title", "property", "status", "relationship",
                  "source_title", "target_title", "value", "subject"):
        if common is not None and field not in common:
            continue
        if field in row:
            parts.append(json.dumps(normalise(row[field]), sort_keys=True))
    if not parts:
        stripped = {k: v for k, v in row.items()
                    if not _ignored(k)}
        parts.append(json.dumps(normalise(stripped), sort_keys=True))
    return "|".join(parts)


class Report:
    def __init__(self, name):
        self.name = name
        self.rows_a = 0
        self.rows_b = 0
        self.only_a = set()
        self.only_b = set()
        self.value_diffs = Counter()
        self.samples = {}
        self.error = None
        self.headers = {}
        self.status_a = None
        self.status_b = None
        self.total_a = None
        self.total_b = None

    def record_totals(self, total_a, total_b) -> None:
        self.total_a, self.total_b = total_a, total_b
        if total_a is not None and total_b is not None and total_a != total_b:
            self.value_diffs[TOTAL_ROWS] += 1
            self.samples[TOTAL_ROWS] = f"pyppetdb={total_a} openvoxdb={total_b}"

    @property
    def truncated(self) -> bool:
        return any(
            total is not None and total > rows
            for rows, total in ((self.rows_a, self.total_a), (self.rows_b, self.total_b))
        )

    @property
    def clean(self) -> bool:
        return (
            self.error is None
            and self.status_a == self.status_b
            and self.rows_a == self.rows_b
            and not self.only_a
            and not self.only_b
            and not self.value_diffs
        )


async def fetch(client, base, path, query, params):
    call = dict(params)
    if query is not None:
        call["query"] = json.dumps(query)
    response = await client.get(f"{base}{path}", params=call)
    if response.status_code >= 400:
        return None, response.headers, response.status_code
    return response.json(), response.headers, response.status_code


async def fetch_all(
    client, base, path, query, params, entity, page_size, max_rows, totals
):
    if entity is None:
        rows, headers, status = await fetch(client, base, path, query, params)
        return rows, headers, status, None
    order_by = json.dumps(
        [{"field": field, "order": "asc"} for field in ORDER_KEYS[entity]]
    )
    rows, total, headers, status, offset = [], None, None, None, 0
    while True:
        call = dict(params, limit=str(page_size), offset=str(offset), order_by=order_by)
        if offset == 0 and totals:
            call["include_total"] = "true"
        page, page_headers, status = await fetch(client, base, path, query, call)
        if offset == 0:
            headers = page_headers
            if status >= 400:
                return page, headers, status, None
            records = page_headers.get("x-records")
            total = int(records) if records is not None else None
        if not isinstance(page, list):
            return page, headers, status, total
        rows.extend(page)
        if (
            len(page) < page_size
            or len(rows) >= max_rows
            or (total is not None and len(rows) >= total)
        ):
            break
        offset += page_size
    return rows, headers, status, total


def compare(name, a, b, headers_a, headers_b) -> Report:
    report = Report(name)
    if not isinstance(a, list):
        a = [a]
    if not isinstance(b, list):
        b = [b]
    report.rows_a, report.rows_b = len(a), len(b)

    keys_a = {key for row in a if isinstance(row, dict) for key in row}
    keys_b = {key for row in b if isinstance(row, dict) for key in row}
    report.only_a = keys_a - keys_b
    report.only_b = keys_b - keys_a

    for header in ("x-records",):
        if headers_a.get(header) != headers_b.get(header):
            report.headers[header] = (
                headers_a.get(header),
                headers_b.get(header),
            )

    common = keys_a & keys_b
    index_b = {}
    for row in b:
        index_b.setdefault(row_key(row, common), []).append(row)
    for row in a:
        matches = index_b.get(row_key(row, common))
        if not matches:
            report.value_diffs["<row missing upstream>"] += 1
            report.samples.setdefault(
                "<row missing upstream>", json.dumps(normalise(row))[:160]
            )
            continue
        other = matches.pop(0)
        if not isinstance(row, dict) or not isinstance(other, dict):
            continue
        for key in keys_a & keys_b:
            if _ignored(key):
                continue
            left, right = normalise(row.get(key)), normalise(other.get(key))
            if key in SET_FIELDS and isinstance(left, list) and isinstance(right, list):
                left, right = sorted(map(str, left)), sorted(map(str, right))
            if _is_child(left) and _is_child(right):
                for part, label in (("data", f"{key}.data"), ("href", f"{key}.href")):
                    if _ignored(label):
                        continue
                    a_part, b_part = left.get(part), right.get(part)
                    if (
                        key in UNORDERED_CHILD_FIELDS
                        and isinstance(a_part, list)
                        and isinstance(b_part, list)
                    ):
                        a_part = sorted(
                            (_canonical_element(e) for e in a_part), key=_stable
                        )
                        b_part = sorted(
                            (_canonical_element(e) for e in b_part), key=_stable
                        )
                    if a_part != b_part:
                        report.value_diffs[label] += 1
                        report.samples.setdefault(
                            label,
                            f"pyppetdb={json.dumps(left.get(part))[:70]} "
                            f"openvoxdb={json.dumps(right.get(part))[:70]}",
                        )
                continue
            if left != right:
                report.value_diffs[key] += 1
                report.samples.setdefault(
                    key,
                    f"pyppetdb={json.dumps(left)[:70]} openvoxdb={json.dumps(right)[:70]}",
                )
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare every pyppetdb /pdb endpoint against OpenVoxDB"
    )
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--fact", default="kernel")
    parser.add_argument("--fact-value", default="Linux")
    parser.add_argument("--type", default="File")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--ca")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--json")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--group", action="append",
        help=f"restrict to a group or origin ({', '.join(GROUPS)})",
    )
    parser.add_argument("--only", help="regex on the case name")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--max-rows", type=int, default=50000)
    parser.add_argument(
        "--totals", action="store_true",
        help="also compare X-Records totals (a count(*) per paged case on both targets; minutes on 10M-row cases)",
    )
    args = parser.parse_args()

    context = ssl.create_default_context(cafile=args.ca)
    if args.cert and args.key:
        context.load_cert_chain(certfile=args.cert, keyfile=args.key)

    cases = CASES
    if args.group:
        selected = []
        for name in args.group:
            if name in GROUPS:
                selected.extend(GROUPS[name])
            else:
                selected.extend(
                    case for group in GROUPS.values() for case in group
                    if case.origin == name
                )
        seen = set()
        cases = [case for case in selected
                 if not (case.name in seen or seen.add(case.name))]
    if args.only:
        pattern = re.compile(args.only)
        cases = [case for case in cases if pattern.search(case.name)]
    if not cases:
        print("keine Faelle ausgewaehlt")
        return 2

    reports = []
    async with httpx.AsyncClient(verify=context, timeout=args.timeout) as client:
        substitutions = {
            "{node}": args.node,
            "{fact}": args.fact,
            "{factvalue}": args.fact_value,
            "{type}": args.type,
            "{environment}": args.environment,
        }
        for case in cases:
            resolved_path = _substitute(case.path, substitutions)
            resolved_query = json.loads(
                _substitute(json.dumps(case.query), substitutions)
            ) if case.query is not None else None
            params = {
                key: _substitute(value, substitutions)
                for key, value in case.params.items()
            }
            entity = _pageable(resolved_path, resolved_query, params)
            try:
                a, headers_a, status_a, total_a = await fetch_all(
                    client, args.a, resolved_path, resolved_query, params,
                    entity, args.page_size, args.max_rows, args.totals,
                )
                b, headers_b, status_b, total_b = await fetch_all(
                    client, args.b, resolved_path, resolved_query, params,
                    entity, args.page_size, args.max_rows, args.totals,
                )
            except Exception as err:
                report = Report(case.name)
                report.error = f"{type(err).__name__}: {err}"[:120]
                reports.append(report)
                continue
            if case.expect_error:
                report = Report(case.name)
                report.status_a, report.status_b = status_a, status_b
                if status_a < 400:
                    report.error = f"pyppetdb accepted it ({status_a})"
                elif status_b < 400:
                    report.error = f"OpenVoxDB accepted it ({status_b})"
                reports.append(report)
                continue
            if status_a >= 400 or status_b >= 400:
                report = Report(case.name)
                report.status_a, report.status_b = status_a, status_b
                report.error = f"HTTP {status_a} vs {status_b}"
                reports.append(report)
                continue
            report = compare(case.name, a, b, headers_a, headers_b)
            report.status_a, report.status_b = status_a, status_b
            report.record_totals(total_a, total_b)
            reports.append(report)

    width = max(len(report.name) for report in reports)
    print(f"{'case':{width}}  {'rows a/b':>12}  status")
    print("-" * (width + 40))
    for report in reports:
        if report.error:
            print(f"{report.name:{width}}  {'-':>12}  ERROR {report.error}")
            continue
        counts = f"{report.rows_a}/{report.rows_b}"
        if report.truncated:
            counts += f" von {report.total_a}/{report.total_b}"
        if report.clean:
            if report.status_a is not None and report.status_a >= 400:
                print(f"{report.name:{width}}  {'-':>12}  "
                      f"beide abgelehnt ({report.status_a}/{report.status_b})")
            elif report.rows_a == 0:
                print(f"{report.name:{width}}  {counts:>12}  identisch (leer)")
            else:
                print(f"{report.name:{width}}  {counts:>12}  identisch")
            continue
        issues = []
        if report.rows_a != report.rows_b:
            issues.append("Zeilenzahl")
        if report.only_a:
            issues.append(f"nur pyppetdb: {', '.join(sorted(report.only_a))}")
        if report.only_b:
            issues.append(f"nur OpenVoxDB: {', '.join(sorted(report.only_b))}")
        if report.headers:
            issues.append(f"header {report.headers}")
        print(f"{report.name:{width}}  {counts:>12}  {'; '.join(issues) or 'Werte'}")
        for key, count in report.value_diffs.most_common():
            marker = "  " if _ignored(key) else "! "
            print(f"{'':{width}}  {'':>12}  {marker}{key}: {count} Zeilen")
            if args.verbose:
                print(f"{'':{width}}  {'':>12}      {report.samples[key]}")

    clean = sum(1 for report in reports if report.clean)
    empty = sum(1 for report in reports
                if report.clean and report.rows_a == 0
                and (report.status_a or 200) < 400)
    print(f"\n{clean}/{len(reports)} Faelle identisch"
          f" ({empty} davon ohne Daten, also ohne Aussagekraft)")
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(
                [
                    {
                        "case": report.name,
                        "rows_a": report.rows_a,
                        "rows_b": report.rows_b,
                        "total_a": report.total_a,
                        "total_b": report.total_b,
                        "only_a": sorted(report.only_a),
                        "only_b": sorted(report.only_b),
                        "value_diffs": dict(report.value_diffs),
                        "samples": report.samples,
                        "error": report.error,
                    }
                    for report in reports
                ],
                handle,
                indent=1,
            )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
