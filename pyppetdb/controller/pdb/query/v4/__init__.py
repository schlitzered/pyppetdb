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

import httpx
from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse

from bson.objectid import ObjectId

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.config import Config
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.helpers.puppetdb import FactsIndexSpec
from pyppetdb.pdb.query import event_counts
from pyppetdb.pdb.query.engine import QueryEngine
from pyppetdb.pdb.query.engine import RowStream
from pyppetdb.pdb.query.engine import _sort_key
from pyppetdb.pdb.query.errors import PuppetDBQueryError
from pyppetdb.pdb.query.paging import Paging
from pyppetdb.pdb.query.paging import parse_paging
from pyppetdb.pdb.query.params import parse_bool
from pyppetdb.pdb.query.params import parse_distinct
from pyppetdb.pdb.query.params import parse_explain
from pyppetdb.pdb.query.params import parse_timeout
from pyppetdb.pdb.query.params import root_entity_restricted
from pyppetdb.pdb.query.params import validate_params


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


class PrettyJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return orjson.dumps(
            content, default=_encode, option=JSON_OPTIONS | orjson.OPT_INDENT_2
        )


def json_response(content, pretty: bool, status_code: int = 200, headers=None):
    cls = PrettyJSONResponse if pretty else PdbJSONResponse
    return cls(content=content, status_code=status_code, headers=headers)


def _dump_batch(batch: list, pretty: bool) -> bytes:
    if not pretty:
        return orjson.dumps(batch, default=_encode, option=JSON_OPTIONS)[1:-1]
    text = orjson.dumps(
        batch, default=_encode, option=JSON_OPTIONS | orjson.OPT_INDENT_2
    )
    return text[2:-2]


async def _stream_body(stream: RowStream, pretty: bool, log, request=None):
    separator = b",\n" if pretty else b","
    written = False
    try:
        async for batch in stream.batches():
            if request is not None and await request.is_disconnected():
                return
            if not batch:
                continue
            chunk = _dump_batch(batch, pretty)
            if written:
                yield separator + chunk
            else:
                yield (b"[\n" if pretty else b"[") + chunk
                written = True
    except Exception as err:
        log.error(f"streaming a /pdb/query/v4 response failed: {err}")
        raise
    finally:
        await stream.close()
    if not written:
        yield b"[]"
    else:
        yield b"\n]" if pretty else b"]"


def stream_response(stream: RowStream, pretty: bool, log, headers=None, request=None):
    return StreamingResponse(
        _stream_body(stream, pretty, log, request),
        media_type="application/json",
        headers=headers,
    )


def not_found(label: str, identifier: str, pretty: bool = False):
    return json_response(
        {"error": f"No information is known about {label} {identifier}"},
        pretty,
        status_code=404,
    )


HOP_HEADERS = (
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
)

NODE_PARENT = ("nodes", "certname", "certname", "node")
REPORT_PARENT = ("reports", "hash", "hash", "report")
CATALOG_PARENT = ("catalogs", "certname", "certname", "catalog")
FACTSET_PARENT = ("factsets", "certname", "certname", "factset")
ENVIRONMENT_PARENT = ("environments", "name", "environment", "environment")
PRODUCER_PARENT = ("producers", "name", "producer", "producer")
SINGLE_LABELS = {
    "nodes": "node",
    "environments": "environment",
    "producers": "producer",
    "catalogs": "catalog",
    "factsets": "factset",
}
CERTNAME = (("certname", "certname"),)


class Route:
    def __init__(
        self,
        path: str,
        entity: str,
        kind: str = "list",
        implicit=(),
        parent=None,
        params: str = "typical",
        restrict: bool = False,
    ):
        self.path = path
        self.entity = entity
        self.kind = kind
        self.implicit = tuple(implicit)
        self.parent = parent
        self.params = params
        self.restrict = restrict


def _fact_routes(prefix: str, implicit, parent) -> list:
    return [
        Route(f"{prefix}/facts", "facts", "list", implicit, parent, "typical", True),
        Route(
            f"{prefix}/facts/{{name}}",
            "facts",
            "list",
            implicit + (("name", "name"),),
            parent,
            "typical",
            True,
        ),
        Route(
            f"{prefix}/facts/{{name}}/{{value:path}}",
            "facts",
            "list",
            implicit + (("name", "name"), ("value", "value")),
            parent,
            "typical",
            True,
        ),
    ]


def _resource_routes(prefix: str, implicit, parent) -> list:
    return [
        Route(
            f"{prefix}/resources", "resources", "list", implicit, parent, "typical", True
        ),
        Route(
            f"{prefix}/resources/{{type}}",
            "resources",
            "list",
            implicit + (("type", "type"),),
            parent,
            "typical",
            True,
        ),
        Route(
            f"{prefix}/resources/{{type}}/{{title:path}}",
            "resources",
            "list",
            implicit + (("type", "type"), ("title", "title")),
            parent,
            "typical",
            True,
        ),
    ]


def _report_routes(prefix: str, implicit, parent) -> list:
    report = implicit + (("hash", "report"),)
    return [
        Route(f"{prefix}/reports", "reports", "list", implicit, parent, "typical"),
        Route(
            f"{prefix}/reports/{{hash}}/events",
            "events",
            "list",
            report,
            REPORT_PARENT,
            "events",
        ),
        Route(
            f"{prefix}/reports/{{hash}}/metrics",
            "reports",
            "metrics",
            implicit + (("hash", "hash"),),
            REPORT_PARENT,
            "status",
        ),
        Route(
            f"{prefix}/reports/{{hash}}/logs",
            "reports",
            "logs",
            implicit + (("hash", "hash"),),
            REPORT_PARENT,
            "status",
        ),
    ]


def _catalog_routes(prefix: str, implicit, parent) -> list:
    certname = implicit + CERTNAME
    return [
        Route(f"{prefix}/catalogs", "catalogs", "list", implicit, parent, "typical"),
        Route(
            f"{prefix}/catalogs/{{certname}}",
            "catalogs",
            "single",
            certname,
            None,
            "status",
        ),
        Route(
            f"{prefix}/catalogs/{{certname}}/edges",
            "edges",
            "list",
            certname,
            CATALOG_PARENT,
            "typical",
            True,
        ),
        *_resource_routes(f"{prefix}/catalogs/{{certname}}", certname, CATALOG_PARENT),
    ]


def _factset_routes(prefix: str, implicit, parent) -> list:
    certname = implicit + CERTNAME
    return [
        Route(
            f"{prefix}/factsets", "factsets", "list", implicit, parent, "typical", True
        ),
        Route(
            f"{prefix}/factsets/{{certname}}",
            "factsets",
            "single",
            certname,
            None,
            "status",
        ),
        Route(
            f"{prefix}/factsets/{{certname}}/facts",
            "factsets",
            "list",
            certname,
            FACTSET_PARENT,
            "typical",
        ),
    ]


def _routes() -> list:
    environment = (("environment", "environment"),)
    producer = (("producer", "producer"),)
    return [
        Route("/nodes", "nodes", "list", (), None, "typical", True),
        Route("/nodes/{certname}", "nodes", "single", CERTNAME, None, "status"),
        *_fact_routes("/nodes/{certname}", CERTNAME, NODE_PARENT),
        *_resource_routes("/nodes/{certname}", CERTNAME, NODE_PARENT),
        Route("/environments", "environments"),
        Route(
            "/environments/{environment}",
            "environments",
            "single",
            (("environment", "name"),),
            None,
            "status",
        ),
        *_fact_routes("/environments/{environment}", environment, ENVIRONMENT_PARENT),
        *_resource_routes(
            "/environments/{environment}", environment, ENVIRONMENT_PARENT
        ),
        *_report_routes("/environments/{environment}", environment, ENVIRONMENT_PARENT),
        Route(
            "/environments/{environment}/events",
            "events",
            "list",
            environment,
            ENVIRONMENT_PARENT,
            "events",
        ),
        Route("/producers", "producers"),
        Route(
            "/producers/{producer}",
            "producers",
            "single",
            (("producer", "name"),),
            None,
            "status",
        ),
        *_factset_routes("/producers/{producer}", producer, PRODUCER_PARENT),
        *_catalog_routes("/producers/{producer}", producer, PRODUCER_PARENT),
        *_report_routes("/producers/{producer}", producer, PRODUCER_PARENT),
        *_fact_routes("", (), None),
        Route("/fact-names", "fact-names"),
        Route("/fact-paths", "fact-paths"),
        Route("/fact-contents", "fact-contents", "list", (), None, "typical", True),
        *_factset_routes("", (), None),
        Route("/inventory", "inventory", "list", (), None, "typical", True),
        *_resource_routes("", (), None),
        Route("/edges", "edges", "list", (), None, "typical", True),
        *_catalog_routes("", (), None),
        Route("/catalog-inputs", "catalog-inputs", "list", (), None, "typical", True),
        Route(
            "/catalog-input-contents",
            "catalog-input-contents",
            "list",
            (),
            None,
            "typical",
            True,
        ),
        Route("/packages", "packages"),
        Route("/package-inventory", "packages", "list", (), None, "typical", True),
        Route("/package-inventory/{certname}", "packages", "list", CERTNAME),
        *_report_routes("", (), None),
        Route("/events", "events", "list", (), None, "events"),
    ]


ENTITY_ROUTES = _routes()


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
        self._post_routes = []

        self._add_route("", self._make_handler(Route("", None, "root", (), None, "root")))
        for route in ENTITY_ROUTES:
            self._add_route(route.path, self._make_handler(route))
        self._add_route("/event-counts", self._make_event_counts_handler(False))
        self._add_route(
            "/aggregate-event-counts", self._make_event_counts_handler(True)
        )
        for path, handler in self._post_routes:
            self._add_method_route(path, handler, "POST")

    def _add_route(self, path: str, handler) -> None:
        self._add_method_route(path, handler, "GET")
        self._post_routes.append((path, handler))

    def _add_method_route(self, path: str, handler, method: str) -> None:
        self.router.add_api_route(
            path,
            handler,
            response_model=None,
            methods=[method],
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

    def _make_handler(self, route: Route):
        async def handler(request: Request):
            await self.authorize_client_cert.require_cn_trusted(request)
            try:
                return await self._dispatch(request, route)
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

    async def _dispatch(self, request: Request, route: Route):
        if self.config.app.puppetdb.query_upstream(route.entity):
            return await self.proxy(request)

        params = await read_params(request)
        validate_params(params, route.params)
        ast = params.get("query")
        entity = route.entity
        restrict = route.restrict
        pretty = parse_bool(params.get("pretty", False))
        if route.kind == "root":
            entity = _root_entity(ast)
            if parse_bool(params.get("ast_only", False)):
                return json_response(ast, pretty)
            restrict = root_entity_restricted(entity)
        timeout = parse_timeout(params.get("timeout"))
        explain = parse_explain(params.get("explain"))
        distinct = parse_distinct(params)
        implicit = build_implicit(request, route.implicit)
        if route.parent is not None:
            parent_entity, column, param, label = route.parent
            identifier = request.path_params.get(param)
            if not await self._exists(parent_entity, column, identifier):
                return not_found(label, identifier, pretty)

        paging = parse_paging(params)
        if explain:
            plan = await self.engine.explain(
                entity_name=entity,
                ast=ast,
                paging=paging,
                implicit=implicit,
                timeout=timeout,
                restrict_active=restrict,
                distinct_window=distinct,
            )
            return json_response(plan, pretty)
        if route.kind in ("metrics", "logs"):
            return await self._report_data(route, implicit, timeout, pretty)

        rows, total = await self.engine.run(
            entity_name=entity,
            ast=ast,
            paging=paging,
            implicit=implicit,
            timeout=timeout,
            restrict_active=restrict,
            extra_columns=_extra_columns(entity, params, route.kind),
            distinct_window=distinct,
            stream=route.kind != "single",
        )
        if route.kind == "single":
            if not rows:
                label = SINGLE_LABELS.get(entity, entity)
                return not_found(label, request.path_params.get(route.implicit[0][0]), pretty)
            return json_response(rows[0], pretty)
        headers = {"X-Records": str(total)} if paging.include_total else None
        if isinstance(rows, RowStream):
            return stream_response(
                rows, pretty, self.log, headers=headers, request=request
            )
        return json_response(rows, pretty, headers=headers)

    async def _exists(self, entity: str, column: str, value) -> bool:
        return await self.engine.exists(entity, column, value)

    async def _report_data(self, route: Route, implicit: list, timeout, pretty: bool):
        rows, _total = await self.engine.run(
            entity_name="reports",
            ast=["extract", [route.kind]],
            paging=Paging(limit=1),
            implicit=implicit,
            timeout=timeout,
        )
        if not rows:
            return not_found("report", implicit[-1][2], pretty)
        value = rows[0].get(route.kind)
        if isinstance(value, dict) and "data" in value:
            value = value["data"]
        return json_response(value if value is not None else [], pretty)

    async def _dispatch_event_counts(self, request: Request, aggregate: bool):
        if self.config.app.puppetdb.query_upstream("events"):
            return await self.proxy(request)

        params = await read_params(request)
        validate_params(
            params, "aggregate-event-counts" if aggregate else "event-counts"
        )
        summarize_by = event_counts.parse_summarize_by(params.get("summarize_by"))
        count_by = event_counts.parse_count_by(params.get("count_by"))
        counts_filter = event_counts.parse_counts_filter(params.get("counts_filter"))
        pretty = parse_bool(params.get("pretty", False))
        distinct = parse_distinct(params)
        timeout = parse_timeout(params.get("timeout"))
        paging = parse_paging(params)

        query = params.get("query")
        results = []
        for field in summarize_by:
            stages = event_counts.summary_stages(field, count_by)
            summed = aggregate and not counts_filter
            if summed:
                stages = stages + event_counts.aggregate_stages()
            counts = await self.engine.group(
                entity_name="events",
                ast=event_counts.extract_columns_query(query),
                stages=stages,
                timeout=timeout,
                distinct_window=distinct,
            )
            counts = event_counts.apply_counts_filter(counts, counts_filter)
            if summed:
                summary = event_counts.aggregate_totals(counts)
                summary["summarize_by"] = field
                results.append(summary)
            elif aggregate:
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
        return json_response(results, pretty, headers=headers)

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
            else:
                raise PuppetDBQueryError("request body must be a JSON map")
    if "query" in params:
        params["query"] = parse_query_param(params["query"])
    if isinstance(params.get("order_by"), list):
        params["order_by"] = json.dumps(params["order_by"])
    if isinstance(params.get("counts_filter"), list):
        params["counts_filter"] = json.dumps(params["counts_filter"])
    return params


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


def _root_entity(ast) -> str:
    if not isinstance(ast, list) or not ast or ast[0] != "from":
        raise PuppetDBQueryError(
            "Queries against the root endpoint must be a 'from' expression"
        )
    entity = ast[1] if len(ast) > 1 and isinstance(ast[1], str) else None
    if entity is None:
        raise PuppetDBQueryError("from requires an entity name")
    return entity


def _extra_columns(entity: str, params: dict, kind: str) -> list:
    extra = []
    normalised = entity.replace("_", "-")
    if normalised == "nodes" and parse_bool(params.get("include_facts_expiration", False)):
        extra.extend(["expires_facts", "expires_facts_updated"])
    if (
        kind != "single"
        and normalised in ("factsets", "inventory")
        and parse_bool(params.get("include_package_inventory", False))
    ):
        extra.append("package_inventory")
    return extra


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
