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
import time
from html import escape
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
    if parts[0] == "factsets" and len(parts) == 3:
        return "factsets"
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


async def _latest_report_hash(client, base: str, node: str) -> str:
    response = await client.get(
        f"{base}/pdb/query/v4/reports",
        params={
            "query": json.dumps(["=", "certname", node]),
            "order_by": json.dumps([{"field": "receive_time", "order": "desc"}]),
            "limit": 1,
        },
    )
    rows = response.json() if response.status_code == 200 else []
    return rows[0].get("hash", "") if rows else ""


async def _node_producer(client, base: str, node: str) -> str:
    response = await client.get(f"{base}/pdb/query/v4/factsets/{node}")
    if response.status_code != 200:
        return ""
    return response.json().get("producer") or ""


async def _node_environment(client, base: str, node: str) -> str:
    response = await client.get(f"{base}/pdb/query/v4/nodes/{node}")
    if response.status_code != 200:
        return "production"
    return response.json().get("report_environment") or "production"


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
        self.path = None
        self.query = None
        self.params = {}
        self.group = None
        self.origin = None
        self.ms_a = None
        self.ms_b = None
        self.body_a = None
        self.body_b = None

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
        return response.text[:2000], response.headers, response.status_code
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


def _row_signature(row, keys) -> str:
    if not isinstance(row, dict):
        return json.dumps(normalise(row), sort_keys=True)
    parts = {}
    for key in sorted(keys):
        if _ignored(key):
            continue
        value = normalise(row.get(key))
        if _is_child(value):
            value = None if _ignored(f"{key}.data") else value.get("data")
            if key in UNORDERED_CHILD_FIELDS and isinstance(value, list):
                value = sorted((_canonical_element(e) for e in value), key=_stable)
        elif key in SET_FIELDS and isinstance(value, list):
            value = sorted(map(str, value))
        parts[key] = value
    return json.dumps(parts, sort_keys=True, default=str)


def _best_match(row, matches: list, keys):
    if len(matches) > 1:
        wanted = _row_signature(row, keys)
        for index, candidate in enumerate(matches):
            if _row_signature(candidate, keys) == wanted:
                return matches.pop(index)
    return matches.pop(0)


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
        other = _best_match(row, matches, keys_a & keys_b)
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


def _annotate(report, case, group_of, path, query, params, ms_a, ms_b, a, b):
    report.path = path
    report.query = query
    report.params = params
    report.group = group_of.get(case.name)
    report.origin = case.origin
    report.ms_a, report.ms_b = ms_a, ms_b
    report.body_a, report.body_b = a, b


HTML_ROWS = 25
HTML_CHARS = 12000


def _body_text(body):
    if body is None:
        return "(keine Antwort)", ""
    if isinstance(body, str):
        return body, ""
    note = ""
    shown = body
    if isinstance(body, list) and len(body) > HTML_ROWS:
        shown = body[:HTML_ROWS]
        note = f"… {len(body) - HTML_ROWS} weitere Zeilen"
    text = json.dumps(shown, indent=1, ensure_ascii=False, default=str)
    if len(text) > HTML_CHARS:
        text = text[:HTML_CHARS] + "\n…"
        note = note or "… gekürzt"
    return text, note


def _ms(value):
    return "–" if value is None else f"{value:,.0f} ms".replace(",", "\u202f")


def _verdict(report):
    if report.error:
        return "error", report.error
    if report.clean:
        if report.status_a is not None and report.status_a >= 400:
            return "ok", f"beide abgelehnt ({report.status_a}/{report.status_b})"
        return "ok", "identisch" + (" (leer)" if report.rows_a == 0 else "")
    issues = []
    if report.rows_a != report.rows_b:
        issues.append("Zeilenzahl")
    if report.only_a:
        issues.append("nur pyppetdb: " + ", ".join(sorted(report.only_a)))
    if report.only_b:
        issues.append("nur OpenVoxDB: " + ", ".join(sorted(report.only_b)))
    if report.value_diffs:
        issues.append("Werte: " + ", ".join(sorted(report.value_diffs)))
    return "diff", "; ".join(issues)


def render_html(reports, args) -> str:
    counts = {"ok": 0, "diff": 0, "error": 0}
    for report in reports:
        counts[_verdict(report)[0]] += 1
    sum_a = sum(r.ms_a or 0 for r in reports)
    sum_b = sum(r.ms_b or 0 for r in reports)
    faster = sum(1 for r in reports if r.ms_a is not None and r.ms_b is not None and r.ms_a < r.ms_b)
    timed = sum(1 for r in reports if r.ms_a is not None and r.ms_b is not None)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    parts = [HTML_HEAD]
    parts.append(
        '<header class="top"><p class="eyebrow">Differential · PuppetDB API v4</p>'
        '<h1>pyppetdb gegen OpenVoxDB</h1>'
        f'<p class="lede">{len(reports)} Fälle, gleiche Daten, gleiche Queries — '
        f'<span class="a">A = pyppetdb</span> {escape(args.a)} · '
        f'<span class="b">B = OpenVoxDB</span> {escape(args.b)} · Node <code>{escape(args.node)}</code> · {stamp}</p>'
        '<div class="tiles">'
        f'<div class="tile ok"><b>{counts["ok"]}</b><span>identisch</span></div>'
        f'<div class="tile diff"><b>{counts["diff"]}</b><span>abweichend</span></div>'
        f'<div class="tile error"><b>{counts["error"]}</b><span>Fehler</span></div>'
        f'<div class="tile"><b>{_ms(sum_a)}</b><span>Summe A</span></div>'
        f'<div class="tile"><b>{_ms(sum_b)}</b><span>Summe B</span></div>'
        f'<div class="tile"><b>{faster}/{timed}</b><span>A schneller</span></div>'
        '</div></header>'
    )
    parts.append('<nav class="index"><div class="scroll"><table><thead><tr><th>Fall</th><th>Gruppe</th><th>Ergebnis</th>'
                 '<th class="num">Zeilen A/B</th><th class="num">A</th><th class="num">B</th></tr></thead><tbody>')
    for index, report in enumerate(reports):
        kind, text = _verdict(report)
        rows = f"{report.rows_a}/{report.rows_b}" if report.status_a is not None and report.status_a < 400 and not report.error else "–"
        parts.append(
            f'<tr class="{kind}"><td><a href="#case-{index}">{escape(report.name)}</a></td>'
            f'<td class="muted">{escape(report.group or "")}</td>'
            f'<td><span class="pill {kind}">{escape(text[:60])}</span></td>'
            f'<td class="num">{rows}</td><td class="num">{_ms(report.ms_a)}</td><td class="num">{_ms(report.ms_b)}</td></tr>'
        )
    parts.append('</tbody></table></div></nav><main>')
    for index, report in enumerate(reports):
        kind, text = _verdict(report)
        call = dict(report.params or {})
        params = " ".join(f"{k}={v}" for k, v in call.items()) if call else "keine"
        query = json.dumps(report.query, ensure_ascii=False) if report.query is not None else "(ohne query)"
        text_a, note_a = _body_text(report.body_a)
        text_b, note_b = _body_text(report.body_b)
        open_attr = "" if kind == "ok" else " open"
        detail = ""
        if report.value_diffs:
            items = "".join(
                f"<li><code>{escape(key)}</code> · {count} Zeilen"
                + (f"<br><small>{escape(str(report.samples.get(key, '')))}</small>" if report.samples.get(key) else "")
                + "</li>"
                for key, count in report.value_diffs.most_common()
            )
            detail = f'<div class="delta"><p class="label">Abweichungen</p><ul>{items}</ul></div>'
        parts.append(
            f'<section class="case {kind}" id="case-{index}">'
            f'<div class="head"><p class="eyebrow">{escape(report.group or "")} · {escape(report.origin or "")}</p>'
            f'<h2>{escape(report.name)}</h2><span class="pill {kind}">{escape(text)}</span></div>'
            f'<div class="query"><p class="label">GET {escape(report.path or "")}</p><pre>{escape(query)}</pre>'
            f'<p class="muted small">Parameter: {escape(params)}</p></div>'
            f'<details class="responses"{open_attr}><summary>Antworten '
            f'<span class="a">A {report.status_a or "–"} · {report.rows_a} Zeilen · {_ms(report.ms_a)}</span>'
            f'<span class="b">B {report.status_b or "–"} · {report.rows_b} Zeilen · {_ms(report.ms_b)}</span></summary>'
            f'<div class="side"><div class="col a"><p class="label">pyppetdb</p><pre>{escape(text_a)}</pre><p class="muted small">{escape(note_a)}</p></div>'
            f'<div class="col b"><p class="label">OpenVoxDB</p><pre>{escape(text_b)}</pre><p class="muted small">{escape(note_b)}</p></div></div></details>'
            f'{detail}</section>'
        )
    parts.append('</main>')
    return "".join(parts)


HTML_HEAD = """<title>pyppetdb vs OpenVoxDB</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{--bg:#f5f7f7;--panel:#ffffff;--ink:#1b2426;--muted:#5d6b6f;--line:#d6dedf;--a:#176d7b;--b:#6b5b95;
--ok:#2c7a4b;--ok-bg:#e6f3ea;--diff:#a8641a;--diff-bg:#fbf0dd;--err:#b23a30;--err-bg:#fbe5e2;--code:#eef2f3;--sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131a1c;--panel:#1b2427;--ink:#e3eaeb;--muted:#96a5a9;--line:#2c393d;--a:#5fc3d2;--b:#b3a5e6;
--ok:#7fd39c;--ok-bg:#183424;--diff:#e6ad5c;--diff-bg:#3a2a12;--err:#f0837a;--err-bg:#3d1c19;--code:#0f1517}}
:root[data-theme="dark"]{--bg:#131a1c;--panel:#1b2427;--ink:#e3eaeb;--muted:#96a5a9;--line:#2c393d;--a:#5fc3d2;--b:#b3a5e6;
--ok:#7fd39c;--ok-bg:#183424;--diff:#e6ad5c;--diff-bg:#3a2a12;--err:#f0837a;--err-bg:#3d1c19;--code:#0f1517}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;padding:0 20px 64px}
.top{max-width:1180px;margin:0 auto;padding-block:36px 20px}
.eyebrow{margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{margin:4px 0 8px;font-size:30px;font-weight:600;text-wrap:balance}
h2{margin:2px 0 0;font-size:19px;font-weight:600}
.lede{margin:0 0 20px;color:var(--muted);max-width:70ch}
.lede code{font-family:var(--mono);font-size:13px}
.a{color:var(--a);font-weight:500}.b{color:var(--b);font-weight:500}
.tiles{display:flex;flex-wrap:wrap;gap:12px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 16px;min-width:120px}
.tile b{display:block;font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.tile span{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.tile.ok b{color:var(--ok)}.tile.diff b{color:var(--diff)}.tile.error b{color:var(--err)}
.index{max-width:1180px;margin:0 auto 32px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:500}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
a{color:inherit}
.muted{color:var(--muted)}.small{font-size:12.5px;margin:6px 0 0}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:500;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.diff{background:var(--diff-bg);color:var(--diff)}.pill.error{background:var(--err-bg);color:var(--err)}
main{max-width:1180px;margin:0 auto;display:grid;gap:22px}
.case{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:6px;padding:16px 20px 18px;scroll-margin-top:16px}
.case.diff{border-left-color:var(--diff)}.case.error{border-left-color:var(--err)}.case.ok{border-left-color:var(--ok)}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin-bottom:12px}
.head .eyebrow{flex-basis:100%}
.head .pill{margin-left:auto}
.label{margin:0 0 4px;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.query pre,.side pre{margin:0;background:var(--code);border-radius:4px;padding:10px 12px;font-family:var(--mono);font-size:12.5px;line-height:1.45;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.responses{margin-top:14px}
.responses summary{cursor:pointer;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline;font-weight:500}
.responses summary span{font-size:13px;font-variant-numeric:tabular-nums}
.side{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
.side .col{min-width:0}
.side pre{max-height:520px;overflow:auto}
.col.a .label{color:var(--a)}.col.b .label{color:var(--b)}
.delta{margin-top:14px;background:var(--diff-bg);border-radius:4px;padding:10px 14px}
.delta ul{margin:4px 0 0;padding-left:18px}
.delta li{margin:2px 0}
.delta code,.lede code{font-family:var(--mono);font-size:12.5px}
summary:focus-visible,a:focus-visible{outline:2px solid var(--a);outline-offset:2px}
@media (max-width:760px){.side{grid-template-columns:1fr}h1{font-size:24px}body{padding:0 16px 48px}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
"""


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
    parser.add_argument("--environment", default=None)
    parser.add_argument("--producer", default=None)
    parser.add_argument("--ca")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--json")
    parser.add_argument("--html")
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

    group_of = {
        case.name: group_name
        for group_name, members in GROUPS.items()
        for case in members
    }
    reports = []
    async with httpx.AsyncClient(verify=context, timeout=args.timeout) as client:
        substitutions = {
            "{node}": args.node,
            "{fact}": args.fact,
            "{factvalue}": args.fact_value,
            "{type}": args.type,
            "{environment}": args.environment
            or await _node_environment(client, args.a, args.node),
            "{producer}": args.producer
            or await _node_producer(client, args.a, args.node),
        }
        hashes = {
            args.a: await _latest_report_hash(client, args.a, args.node),
            args.b: await _latest_report_hash(client, args.b, args.node),
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
            path_a = _substitute(resolved_path, {"{hash}": hashes[args.a]})
            path_b = _substitute(resolved_path, {"{hash}": hashes[args.b]})
            a = b = None
            ms_a = ms_b = None
            try:
                started = time.perf_counter()
                a, headers_a, status_a, total_a = await fetch_all(
                    client, args.a, path_a, resolved_query, params,
                    entity, args.page_size, args.max_rows, args.totals,
                )
                ms_a = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                b, headers_b, status_b, total_b = await fetch_all(
                    client, args.b, path_b, resolved_query, params,
                    entity, args.page_size, args.max_rows, args.totals,
                )
                ms_b = (time.perf_counter() - started) * 1000
            except Exception as err:
                report = Report(case.name)
                report.error = f"{type(err).__name__}: {err}"[:120]
                _annotate(report, case, group_of, resolved_path, resolved_query, params, ms_a, ms_b, a, b)
                reports.append(report)
                continue
            if case.expect_error:
                report = Report(case.name)
                report.status_a, report.status_b = status_a, status_b
                if status_a < 400:
                    report.error = f"pyppetdb accepted it ({status_a})"
                elif status_b < 400:
                    report.error = f"OpenVoxDB accepted it ({status_b})"
                _annotate(report, case, group_of, resolved_path, resolved_query, params, ms_a, ms_b, a, b)
                reports.append(report)
                continue
            if status_a >= 400 or status_b >= 400:
                report = Report(case.name)
                report.status_a, report.status_b = status_a, status_b
                report.error = f"HTTP {status_a} vs {status_b}"
                _annotate(report, case, group_of, resolved_path, resolved_query, params, ms_a, ms_b, a, b)
                reports.append(report)
                continue
            report = compare(case.name, a, b, headers_a, headers_b)
            report.status_a, report.status_b = status_a, status_b
            report.record_totals(total_a, total_b)
            _annotate(report, case, group_of, resolved_path, resolved_query, params, ms_a, ms_b, a, b)
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
    if args.html:
        with open(args.html, "w") as handle:
            handle.write(render_html(reports, args))
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
                        "ms_a": report.ms_a,
                        "ms_b": report.ms_b,
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
