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

import orjson
import logging
import ssl
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse

from bson.objectid import ObjectId

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.helpers.puppetdb import FactsIndexSpec
from pyppetdb.pdbquery import event_counts
from pyppetdb.pdbquery.engine import QueryEngine
from pyppetdb.pdbquery.engine import _sort_key
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.paging import parse_paging


def _encode(value):
    if isinstance(value, datetime):
        text = value.isoformat()
        if text.endswith("+00:00"):
            return text[:-6] + "Z"
        if value.tzinfo is None:
            return text + "Z"
        return text
    if isinstance(value, ObjectId):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


JSON_OPTIONS = orjson.OPT_UTC_Z | orjson.OPT_NAIVE_UTC


class PdbJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return orjson.dumps(content, default=_encode, option=JSON_OPTIONS)


HOP_HEADERS = (
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
)

ENTITY_ROUTES = (
    ("/nodes", "nodes", False, ()),
    ("/nodes/{certname}", "nodes", True, (("certname", "certname"),)),
    ("/nodes/{certname}/facts", "facts", False, (("certname", "certname"),)),
    ("/nodes/{certname}/resources", "resources", False, (("certname", "certname"),)),
    ("/environments", "environments", False, ()),
    ("/environments/{environment}", "environments", True, (("environment", "name"),)),
    (
        "/environments/{environment}/facts",
        "facts",
        False,
        (("environment", "environment"),),
    ),
    (
        "/environments/{environment}/resources",
        "resources",
        False,
        (("environment", "environment"),),
    ),
    (
        "/environments/{environment}/reports",
        "reports",
        False,
        (("environment", "environment"),),
    ),
    (
        "/environments/{environment}/events",
        "events",
        False,
        (("environment", "environment"),),
    ),
    ("/producers", "producers", False, ()),
    ("/producers/{producer}", "producers", True, (("producer", "name"),)),
    ("/facts", "facts", False, ()),
    ("/facts/{name}", "facts", False, (("name", "name"),)),
    (
        "/facts/{name}/{value:path}",
        "facts",
        False,
        (("name", "name"), ("value", "value")),
    ),
    ("/fact-names", "fact-names", False, ()),
    ("/fact-paths", "fact-paths", False, ()),
    ("/fact-contents", "fact-contents", False, ()),
    ("/factsets", "factsets", False, ()),
    ("/inventory", "inventory", False, ()),
    ("/resources", "resources", False, ()),
    ("/resources/{type}", "resources", False, (("type", "type"),)),
    (
        "/resources/{type}/{title:path}",
        "resources",
        False,
        (("type", "type"), ("title", "title")),
    ),
    ("/edges", "edges", False, ()),
    ("/catalogs", "catalogs", False, ()),
    ("/catalogs/{certname}", "catalogs", True, (("certname", "certname"),)),
    ("/catalogs/{certname}/edges", "edges", False, (("certname", "certname"),)),
    (
        "/catalogs/{certname}/resources",
        "resources",
        False,
        (("certname", "certname"),),
    ),
    ("/catalog-inputs", "catalog-inputs", False, ()),
    ("/catalog-input-contents", "catalog-input-contents", False, ()),
    ("/packages", "packages", False, ()),
    ("/package-inventory", "packages", False, ()),
    ("/reports", "reports", False, ()),
    ("/reports/{hash}/events", "events", False, (("hash", "report"),)),
    ("/events", "events", False, ()),
)


class ControllerPdbQueryV4:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_reports: CrudNodesReports,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._config = config
        self._http = None
        self._authorize_client_cert = authorize_client_cert
        self._engine = QueryEngine(
            log=log,
            collections={
                "nodes": crud_nodes.coll,
                "nodes_reports": crud_nodes_reports.coll,
                "nodes_resources": crud_nodes.coll.database["nodes_resources"],
                "nodes_edges": crud_nodes.coll.database["nodes_edges"],
                "nodes_events": crud_nodes.coll.database["nodes_events"],
            },
            max_query_depth=config.app.puppetdb.maxQueryDepth,
            max_subquery_depth=config.app.puppetdb.maxSubqueryDepth,
            query_timeout=config.app.puppetdb.queryTimeout,
            query_timeout_max=config.app.puppetdb.queryTimeoutMax,
            max_page_size=config.app.puppetdb.maxPageSize,
            facts_index=FactsIndexSpec(
                max_value_len=config.app.main.facts.indexMaxValueLen,
                depth=config.app.main.facts.indexDepth,
                deny=config.app.main.facts.indexDeny,
            ),
        )
        self._router = APIRouter(tags=["pdb_query_v4"])

        self._add_route("", self._make_handler(None, False, ()))
        for path, entity, single, implicit in ENTITY_ROUTES:
            self._add_route(path, self._make_handler(entity, single, implicit))
        self._add_route("/event-counts", self._make_event_counts_handler(False))
        self._add_route(
            "/aggregate-event-counts", self._make_event_counts_handler(True)
        )

    def _add_route(self, path: str, handler) -> None:
        self.router.add_api_route(
            path,
            handler,
            response_model=None,
            methods=["GET", "POST"],
            status_code=200,
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def config(self) -> Config:
        return self._config

    @property
    def engine(self) -> QueryEngine:
        return self._engine

    @property
    def log(self):
        return self._log

    @property
    def router(self):
        return self._router

    @property
    def http(self) -> httpx.AsyncClient:
        if not self._http:
            if self.config.app.main.ssl:
                ssl_ctx = ssl.create_default_context(cafile=self.config.app.main.ssl.ca)
                ssl_ctx.load_cert_chain(
                    certfile=self.config.app.main.ssl.cert,
                    keyfile=self.config.app.main.ssl.key,
                )
                self._http = httpx.AsyncClient(
                    verify=ssl_ctx,
                    timeout=self.config.app.puppetdb.timeout,
                )
            else:
                self._http = httpx.AsyncClient(
                    timeout=self.config.app.puppetdb.timeout,
                )
        return self._http

    def _make_handler(self, entity: Optional[str], single: bool, implicit):
        async def handler(request: Request):
            await self.authorize_client_cert.require_cn_trusted(request)
            try:
                return await self._dispatch(request, entity, single, implicit)
            except PuppetDBQueryError as err:
                return PlainTextResponse(err.message, status_code=err.status_code)

        return handler

    def _make_event_counts_handler(self, aggregate: bool):
        async def handler(request: Request):
            await self.authorize_client_cert.require_cn_trusted(request)
            try:
                return await self._dispatch_event_counts(request, aggregate)
            except PuppetDBQueryError as err:
                return PlainTextResponse(err.message, status_code=err.status_code)

        return handler

    async def _dispatch(
        self,
        request: Request,
        entity: Optional[str],
        single: bool,
        implicit,
    ):
        if self.config.app.puppetdb.query_upstream(entity):
            return await self.proxy(request)

        params = await read_params(request)
        ast = params["query"]
        if entity is None:
            if not isinstance(ast, list) or not ast or ast[0] != "from":
                raise PuppetDBQueryError(
                    "Queries against the root endpoint must be a 'from' expression"
                )
            entity = ast[1] if len(ast) > 1 and isinstance(ast[1], str) else None
            if entity is None:
                raise PuppetDBQueryError("from requires an entity name")

        paging = parse_paging(params)
        clauses = build_implicit(request, implicit)
        rows, total = await self.engine.run(
            entity_name=entity,
            ast=ast,
            paging=paging,
            implicit=clauses,
            timeout=parse_timeout(params.get("timeout")),
        )
        if single:
            if not rows:
                return PlainTextResponse("", status_code=404)
            return PdbJSONResponse(content=rows[0])
        headers = {"X-Records": str(total)} if paging.include_total else None
        return PdbJSONResponse(content=rows, headers=headers)

    async def _dispatch_event_counts(self, request: Request, aggregate: bool):
        if self.config.app.puppetdb.query_upstream("events"):
            return await self.proxy(request)

        params = await read_params(request)
        summarize_by = event_counts.parse_summarize_by(params.get("summarize_by"))
        count_by = event_counts.parse_count_by(params.get("count_by"))
        counts_filter = event_counts.parse_counts_filter(params.get("counts_filter"))
        paging = parse_paging(params)

        query = params["query"]
        results = []
        for field in summarize_by:
            counts = await self.engine.group(
                entity_name="events",
                ast=event_counts.extract_columns_query(query),
                stages=event_counts.summary_stages(field, count_by, query),
                extra=event_counts.summary_projection(field, count_by, query),
                timeout=parse_timeout(params.get("timeout")),
            )
            counts = event_counts.apply_counts_filter(counts, counts_filter)
            if aggregate:
                summary = event_counts.aggregate(counts)
                summary["summarize_by"] = field
                results.append(summary)
            else:
                results.extend(counts)

        if not aggregate:
            results = apply_local_paging(results, paging)
        headers = (
            {"X-Records": str(len(results))} if paging.include_total else None
        )
        return PdbJSONResponse(content=results, headers=headers)

    async def proxy(self, request: Request) -> Response:
        if not self.config.app.puppetdb.serverurl:
            raise PuppetDBQueryError(
                "no upstream PuppetDB configured", status_code=502
            )
        url = f"{self.config.app.puppetdb.serverurl}{request.url.path}"
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_HEADERS
        }
        body = await request.body()
        upstream = await self.http.request(
            method=request.method,
            url=url,
            params=request.query_params,
            headers=headers,
            content=body or None,
        )
        passthrough = {}
        for name in ("content-type", "x-records"):
            if name in upstream.headers:
                passthrough[name] = upstream.headers[name]
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=passthrough,
        )


async def read_params(request: Request) -> dict:
    params = dict(request.query_params)
    if request.method == "POST":
        raw = await request.body()
        if raw:
            try:
                body = json.loads(raw)
            except ValueError as err:
                raise PuppetDBQueryError(f"malformed JSON body: {err}")
            if isinstance(body, dict):
                for key, value in body.items():
                    params[key] = value
            elif isinstance(body, list):
                params["query"] = body
            else:
                raise PuppetDBQueryError(
                    "request body must be a JSON object or array"
                )
    params["query"] = parse_query_param(params.get("query"))
    if isinstance(params.get("order_by"), list):
        params["order_by"] = json.dumps(params["order_by"])
    if isinstance(params.get("counts_filter"), list):
        params["counts_filter"] = json.dumps(params["counts_filter"])
    return params


def parse_timeout(raw) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        seconds = int(str(raw))
    except ValueError:
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :timeout; expected a positive integer"
        )
    if seconds < 0:
        raise PuppetDBQueryError(
            f"Illegal value '{raw}' for :timeout; expected a positive integer"
        )
    return seconds


def parse_query_param(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        raise PuppetDBQueryError(f"{raw!r} is not a valid query")
    text = raw.strip()
    if not text.startswith("["):
        raise PuppetDBQueryError(
            "PQL queries are not supported; supply an AST query as a JSON array"
        )
    try:
        return json.loads(text)
    except ValueError as err:
        raise PuppetDBQueryError(f"malformed query: {err}")


def build_implicit(request: Request, implicit) -> list:
    clauses = []
    for param, column in implicit:
        value = request.path_params.get(param)
        if value is not None:
            clauses.append(["=", column, value])
    return clauses


def apply_local_paging(rows: list, paging) -> list:
    if paging.order_by:
        for column, order in reversed(paging.order_by):
            rows.sort(
                key=lambda row: _sort_key(row.get(column)),
                reverse=order < 0,
            )
    start = paging.offset or 0
    if paging.limit:
        return rows[start:start + paging.limit]
    return rows[start:]
