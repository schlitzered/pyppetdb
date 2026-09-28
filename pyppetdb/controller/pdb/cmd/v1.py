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

from datetime import datetime
from datetime import UTC
import asyncio
import functools
import gzip
import logging
import ssl
import time
from typing import Optional
import uuid

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request
import httpx
import json

from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.nodes_resources import CrudNodesResources
from pyppetdb.crud.nodes_edges import CrudNodesEdges
from pyppetdb.crud.nodes_events import CrudNodesEvents

from pyppetdb.helpers.placement import calculate_placement
from pyppetdb.helpers.puppetdb import build_resource_documents
from pyppetdb.helpers.puppetdb import build_edge_documents
from pyppetdb.helpers.puppetdb import build_event_documents
from pyppetdb.helpers.puppetdb import catalog_metadata
from pyppetdb.helpers.puppetdb import catalog_payload
from pyppetdb.helpers.puppetdb import normalise_catalog_inputs
from pyppetdb.helpers.puppetdb import normalise_package_inventory
from pyppetdb.helpers.puppetdb import parse_wire_timestamp
from pyppetdb.helpers.puppetdb import report_payload
from pyppetdb.helpers.puppetdb import stable_hash
from pyppetdb.errors import IngestOverloaded
from pyppetdb.errors import ResourceNotFound
from pyppetdb.ingest import IngestQueue

from pyppetdb.model.pdb_facts import PuppetDBFacts
from pyppetdb.model.nodes import NodePutInternal
from pyppetdb.model.nodes_catalogs import NodeCatalogPostInternal
from pyppetdb.model.nodes_reports import NodeReportPostInternal

GZIP_MAGIC = b"\x1f\x8b"


def _decode_command_body(body: bytes, is_gzip: bool) -> tuple:
    raw = gzip.decompress(body) if is_gzip else body
    return raw, json.loads(raw)


def _catalog_documents(
    node_id: str,
    placement,
    environment,
    disabled: bool,
    catalog: dict,
) -> tuple:
    return (
        build_resource_documents(
            node_id=node_id,
            placement=placement,
            environment=environment,
            disabled=disabled,
            resources=catalog.get("resources"),
        ),
        build_edge_documents(
            node_id=node_id,
            placement=placement,
            environment=environment,
            disabled=disabled,
            edges=catalog.get("edges"),
        ),
    )


class ControllerPdbCmdV1:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_catalog_cache: CrudNodesCatalogCache,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
        crud_nodes_resources: CrudNodesResources,
        crud_nodes_edges: CrudNodesEdges,
        crud_nodes_events: CrudNodesEvents,
        authorize_client_cert: AuthorizeClientCert,
        ingest_queue: IngestQueue,
    ):
        self._log = log
        self._ingest_queue = ingest_queue
        self._http = None
        self._config = config
        self._crud_nodes = crud_nodes
        self._crud_nodes_catalog_cache = crud_nodes_catalog_cache
        self._crud_nodes_catalogs = crud_nodes_catalogs
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_nodes_reports = crud_nodes_reports
        self._crud_nodes_resources = crud_nodes_resources
        self._crud_nodes_edges = crud_nodes_edges
        self._crud_nodes_events = crud_nodes_events
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter(
            prefix="/v1",
            tags=["pdb_api_v1"],
        )

        self.router.add_api_route(
            "",
            self.create,
            response_model=None,
            response_model_exclude_unset=True,
            methods=["POST"],
            status_code=200,
        )

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def config(self) -> Config:
        return self._config

    @property
    def ingest_queue(self) -> IngestQueue:
        return self._ingest_queue

    @property
    def crud_nodes(self):
        return self._crud_nodes

    @property
    def crud_nodes_catalogs(self):
        return self._crud_nodes_catalogs

    @property
    def crud_nodes_resources(self):
        return self._crud_nodes_resources

    @property
    def crud_nodes_edges(self):
        return self._crud_nodes_edges

    @property
    def crud_nodes_events(self):
        return self._crud_nodes_events

    @property
    def crud_nodes_catalog_cache(self):
        return self._crud_nodes_catalog_cache

    @property
    def crud_nodes_group(self):
        return self._crud_nodes_groups

    @property
    def crud_nodes_reports(self):
        return self._crud_nodes_reports

    @property
    def log(self):
        return self._log

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

    @property
    def router(self):
        return self._router

    async def create(
        self,
        request: Request,
        certname=Query(),
        command=Query(),
        producer_timestamp=Query(default=None, alias="producer-timestamp"),
        version=Query(),
    ):
        await self.authorize_client_cert.require_cn_trusted(request)
        body = await request.body()
        is_gzip = request.headers.get(
            "content-encoding", ""
        ).lower() == "gzip" or body.startswith(GZIP_MAGIC)
        body_json_bytes, data_decomp = await asyncio.to_thread(
            _decode_command_body, body, is_gzip
        )

        _datetime = datetime.now(UTC)
        start_time_ns = time.perf_counter_ns()
        result = {
            "change_last": _datetime,
            "disabled": False,
            "environment": data_decomp.get("environment"),
        }
        producer_timestamp = parse_wire_timestamp(
            data_decomp.get("producer_timestamp") or producer_timestamp
        )
        if producer_timestamp:
            result["producer_timestamp"] = producer_timestamp
        if data_decomp.get("producer"):
            result["producer"] = data_decomp["producer"]

        job = None
        if command == "replace_facts":
            result["change_facts"] = _datetime
            facts = PuppetDBFacts(**data_decomp)
            result["facts"] = facts.values
            result["facts_hash"] = stable_hash(facts.values)
            packages = normalise_package_inventory(
                data_decomp.get("package_inventory")
            )
            if packages is not None:
                result["package_inventory"] = packages
            job = functools.partial(
                self._job_replace_facts,
                node_id=certname,
                facts=facts,
                base=result,
            )
        elif command == "replace_catalog":
            result["change_catalog"] = _datetime
            catalog = await asyncio.to_thread(catalog_payload, data_decomp)
            job = functools.partial(
                self._job_replace_catalog,
                node_id=certname,
                catalog=catalog,
                catalog_uuid=data_decomp["catalog_uuid"],
                base=result,
                created=_datetime,
            )
        elif command == "replace_catalog_inputs":
            result["catalog_inputs"] = {
                "catalog_uuid": data_decomp.get("catalog_uuid"),
                "producer_timestamp": producer_timestamp,
                "inputs": normalise_catalog_inputs(data_decomp.get("inputs")),
            }
            job = functools.partial(
                self._job_update_node, node_id=certname, base=result
            )
        elif command == "deactivate_node":
            result["disabled"] = True
            job = functools.partial(
                self._job_update_node, node_id=certname, base=result
            )
        elif command == "store_report":
            result["change_report"] = _datetime
            result["report"] = await asyncio.to_thread(
                report_payload, {**data_decomp, "certname": certname}
            )
            job = functools.partial(
                self._job_store_report,
                node_id=certname,
                base=result,
                catalog_uuid=data_decomp.get("catalog_uuid"),
                received=_datetime,
            )

        jobs = []
        if job is not None:
            jobs.append(job)
        if self.config.app.puppetdb.serverurl:
            jobs.append(
                functools.partial(
                    self._job_proxy_to_puppetdb,
                    params=dict(request.query_params),
                    headers=self._proxy_headers(request),
                    body=body_json_bytes,
                )
            )

        if not await self.ingest_queue.enqueue(
            jobs, wait_timeout=self.config.app.puppetdb.writeQueueWaitTimeout
        ):
            raise IngestOverloaded()

        stop_time_ns = time.perf_counter_ns()
        duration_ms = (stop_time_ns - start_time_ns) / 1_000_000
        self.log.info(f"create {command} took {duration_ms:.2f} ms")

        return {"uuid": str(uuid.uuid4())}

    async def _job_update_node(self, node_id: str, base: dict) -> None:
        await self.crud_nodes.update(
            _id=node_id,
            payload=NodePutInternal(**base),
            fields=["id"],
            upsert=True,
            return_none=True,
        )
        await self._propagate_node_state(node_id=node_id, base=base)

    async def _propagate_node_state(self, node_id: str, base: dict) -> None:
        if "disabled" not in base:
            return
        disabled = bool(base["disabled"])
        await self.crud_nodes_reports.set_node_disabled(
            node_id=node_id,
            disabled=disabled,
        )
        await self.crud_nodes_resources.set_node_disabled(
            node_id=node_id,
            disabled=disabled,
        )
        await self.crud_nodes_edges.set_node_disabled(
            node_id=node_id,
            disabled=disabled,
        )
        await self.crud_nodes_events.set_node_disabled(
            node_id=node_id,
            disabled=disabled,
        )

    async def _job_replace_facts(
        self,
        node_id: str,
        facts: PuppetDBFacts,
        base: dict,
    ) -> None:
        base = dict(base)
        base["node_groups"] = await self.crud_nodes_group.reevaluate_node_membership(
            node_id=node_id,
            node_facts=facts,
        )
        await self._update_facts_and_placement_async(
            node_id=node_id,
            payload=NodePutInternal(**base),
        )
        await self._propagate_node_state(node_id=node_id, base=base)

    async def _job_replace_catalog(
        self,
        node_id: str,
        catalog: dict,
        catalog_uuid: str,
        base: dict,
        created: datetime,
    ) -> None:
        base = dict(base)
        metadata = None
        state = await self.crud_nodes.get_ingest_state(_id=node_id)
        if state is None or not state["has_facts"]:
            self.log.warning(
                f"discarding catalog for {node_id}: no facts have been stored yet"
            )
            return
        changed = (
            not catalog.get("catalog_uuid")
            or state["catalog_uuid"] != catalog.get("catalog_uuid")
        )
        if changed:
            base["catalog"] = catalog_metadata(catalog)
        else:
            metadata = catalog_metadata(catalog)
            self.log.debug(
                f"catalog {catalog.get('catalog_uuid')} for {node_id} already stored, keeping resources and "
                f"edges, updating {len(metadata)} catalog metadata fields"
            )
        await self._job_update_node(node_id=node_id, base=base)
        if changed:
            placement = base.get("placement") or state.get("placement")
            resource_docs, edge_docs = await asyncio.to_thread(
                _catalog_documents,
                node_id,
                placement,
                base.get("environment"),
                bool(base.get("disabled", False)),
                catalog,
            )
            await self.crud_nodes_resources.replace_for_node(
                node_id=node_id,
                placement=placement,
                docs=resource_docs,
            )
            await self.crud_nodes_edges.replace_for_node(
                node_id=node_id,
                placement=placement,
                docs=edge_docs,
            )
        if metadata is not None:
            await self.crud_nodes.update_catalog_metadata(
                _id=node_id,
                metadata=metadata,
            )
        if self.config.app.main.storeHistory.catalog:
            await self._store_catalog_history_async(
                node_id=node_id,
                catalog_uuid=catalog_uuid,
                catalog=catalog,
                created=created,
            )

    async def _job_store_report(
        self,
        node_id: str,
        base: dict,
        catalog_uuid: Optional[str],
        received: datetime,
    ) -> None:
        state = await self.crud_nodes.get_ingest_state(_id=node_id)
        if state is None or not state["has_catalog"]:
            self.log.warning(
                f"discarding report for {node_id}: no catalog has been stored yet"
            )
            return
        await self._job_update_node(node_id=node_id, base=base)
        placement = await self.crud_nodes.get_placement(_id=node_id)
        latest, stored = await self.crud_nodes_reports.create_latest(
            _id=received,
            node_id=node_id,
            payload=NodeReportPostInternal(
                **{"placement": placement, "report": base["report"]},
            ),
        )
        if latest:
            await self.crud_nodes_events.set_latest(node_id=node_id, latest=False)
        await self.crud_nodes_events.insert_for_report(
            await asyncio.to_thread(
                build_event_documents,
                node_id,
                placement,
                False,
                received,
                stored["report"],
                latest,
            )
        )
        if not latest:
            self.log.info(
                f"report for {node_id} stored as not latest, a newer report is already stored"
            )
        if not self.config.app.main.storeHistory.catalog:
            return
        if (
            self.config.app.main.storeHistory.catalogUnchanged
            or base["report"]["status"] != "unchanged"
        ):
            await self.crud_nodes_catalogs.drop_created_no_report_ttl(
                _id=catalog_uuid,
                node_id=node_id,
                placement=placement,
            )

    async def _store_catalog_history_async(
        self,
        node_id: str,
        catalog_uuid: str,
        catalog: dict,
        created: datetime,
    ):
        placement = await self.crud_nodes.get_placement(_id=node_id)
        payload = await asyncio.to_thread(
            NodeCatalogPostInternal,
            placement=placement,
            created=created,
            created_no_report_ttl=created,
            catalog=catalog,
        )
        await self.crud_nodes_catalogs.create(
            _id=catalog_uuid,
            node_id=node_id,
            payload=payload,
            fields=["id"],
            return_none=True,
        )

    @staticmethod
    def _proxy_headers(request: Request) -> dict:
        headers = dict(request.headers)
        for name in (
            "content-encoding",
            "x-uncompressed-length",
            "host",
            "content-length",
            "transfer-encoding",
        ):
            headers.pop(name, None)
        return headers

    async def _job_proxy_to_puppetdb(
        self,
        params: dict,
        headers: dict,
        body: bytes,
    ) -> None:
        await self.http.post(
            url=f"{self.config.app.puppetdb.serverurl}/pdb/cmd/v1",
            params=params,
            headers=headers,
            content=body,
        )

    async def _update_facts_and_placement_async(
        self,
        node_id: str,
        payload: NodePutInternal,
    ):
        old_placement = {}
        try:
            old_placement = await self.crud_nodes.get_placement(_id=node_id)
        except ResourceNotFound:
            pass

        await self.crud_nodes.update(
            _id=node_id,
            payload=payload,
            fields=["id"],
            upsert=True,
            return_none=True,
        )

        if payload.facts is not None:
            new_placement = calculate_placement(
                config=self.config,
                facts=payload.facts,
            )
            if old_placement != new_placement:
                await self.crud_nodes_reports.update_placement(
                    node_id=node_id,
                    placement=new_placement,
                )
                await self.crud_nodes_events.update_placement(
                    node_id=node_id,
                    placement=new_placement,
                )
                await self.crud_nodes_catalogs.update_placement(
                    node_id=node_id,
                    placement=new_placement,
                )
                await self.crud_nodes_catalog_cache.update_placement(
                    node_id=node_id,
                    placement=new_placement,
                )
