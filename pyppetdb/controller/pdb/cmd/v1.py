import asyncio
from datetime import datetime
from datetime import UTC
import gzip
import logging
import ssl
import time

from fastapi import APIRouter
from fastapi import Query
from fastapi import Request
import httpx
import orjson

from pyppetdb.config import Config

from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs
from pyppetdb.crud.nodes_groups import CrudNodesGroups
from pyppetdb.crud.nodes_reports import CrudNodesReports

from pyppetdb.model.pdb_facts import PuppetDBFacts
from pyppetdb.model.nodes import NodePutInternal
from pyppetdb.model.nodes_catalogs import NodeCatalogPostInternal
from pyppetdb.model.nodes_reports import NodeReportPostInternal

GZIP_MAGIC = b"\x1f\x8b"


class ControllerPdbCmdV1:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_nodes: CrudNodes,
        crud_nodes_catalogs: CrudNodesCatalogs,
        crud_nodes_groups: CrudNodesGroups,
        crud_nodes_reports: CrudNodesReports,
    ):
        self._log = log
        self._http = None
        self._config = config
        self._crud_nodes = crud_nodes
        self._crud_nodes_catalogs = crud_nodes_catalogs
        self._crud_nodes_groups = crud_nodes_groups
        self._crud_nodes_reports = crud_nodes_reports
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
            status_code=201,
        )

    @property
    def config(self) -> Config:
        return self._config

    @property
    def crud_nodes(self):
        return self._crud_nodes

    @property
    def crud_nodes_catalogs(self):
        return self._crud_nodes_catalogs

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
            ssl_ctx = ssl.create_default_context(cafile=self.config.app.puppetdb.ssl.ca)
            ssl_ctx.load_cert_chain(
                certfile=self.config.app.puppetdb.ssl.cert,
                keyfile=self.config.app.puppetdb.ssl.key,
            )
            self._http = httpx.AsyncClient(verify=ssl_ctx)
        return self._http

    @property
    def router(self):
        return self._router

    async def create(
        self,
        request: Request,
        certname=Query(),
        command=Query(),
        producer_timestamp=Query(alias="producer-timestamp"),
        version=Query(),
    ):
        body = await request.body()
        is_gzip = request.headers.get(
            "content-encoding", ""
        ).lower() == "gzip" or body.startswith(GZIP_MAGIC)
        if is_gzip:
            body_json_bytes = gzip.decompress(body)
        else:
            body_json_bytes = body

        data_decomp = orjson.loads(body_json_bytes)

        _datetime = datetime.now(UTC)
        start_time_ns = time.perf_counter_ns()
        result = {
            "placement": self.config.mongodb.placement,
            "change_last": _datetime,
            "disabled": False,
            "environment": data_decomp["environment"],
        }

        if command == "replace_facts":
            result["change_facts"] = _datetime
            facts = PuppetDBFacts(**data_decomp)
            result["facts"] = facts.values
            groups = await self.crud_nodes_group.reevaluate_node_membership(
                node_id=certname,
                node_facts=facts,
            )
            result["node_groups"] = groups
            asyncio.create_task(
                self.crud_nodes.update(
                    _id=certname,
                    payload=NodePutInternal(**result),
                    fields=["id"],
                    upsert=True,
                    return_none=True,
                )
            )
        elif command == "replace_catalog":
            result["change_catalog"] = _datetime
            result["placement"] = self.config.mongodb.placement
            all_resources = data_decomp["resources"]
            exported_resources = [r for r in all_resources if r.get("exported")]
            result["catalog"] = {
                "catalog_uuid": data_decomp["catalog_uuid"],
                "num_resources": len(all_resources),
                "num_resources_exported": len(exported_resources),
                "resources": all_resources,
                "resources_exported": exported_resources,
            }
            asyncio.create_task(
                self.crud_nodes.update(
                    _id=certname,
                    payload=NodePutInternal(**result),
                    fields=["id"],
                    upsert=True,
                    return_none=True,
                )
            )
            if self.config.app.main.storeHistory.catalog:
                asyncio.create_task(
                    self.crud_nodes_catalogs.create(
                        _id=data_decomp["catalog_uuid"],
                        node_id=certname,
                        payload=NodeCatalogPostInternal(
                            **{
                                "placement": self.config.mongodb.placement,
                                "created": _datetime,
                                "created_no_report_ttl": _datetime,
                                "catalog": result["catalog"],
                            }
                        ),
                        fields=["id"],
                        return_none=True,
                    ),
                )
        elif command == "store_report":
            result["change_report"] = _datetime
            result["report"] = {
                "catalog_uuid": data_decomp["catalog_uuid"],
                "status": data_decomp["status"],
                "noop": data_decomp["noop"],
                "noop_pending": data_decomp["noop_pending"],
                "corrective_change": data_decomp["corrective_change"],
                "logs": data_decomp["logs"],
                "metrics": data_decomp["metrics"],
                "resources": data_decomp["resources"],
            }
            asyncio.create_task(
                self.crud_nodes.update(
                    _id=certname,
                    payload=NodePutInternal(**result),
                    fields=["id"],
                    upsert=True,
                    return_none=True,
                )
            )
            asyncio.create_task(
                self.crud_nodes_reports.create(
                    _id=_datetime,
                    node_id=certname,
                    payload=NodeReportPostInternal(
                        **{
                            "placement": self.config.mongodb.placement,
                            "report": result["report"],
                        },
                    ),
                    fields=["id"],
                    return_none=True,
                )
            )
            if self.config.app.main.storeHistory.catalog:
                if self.config.app.main.storeHistory.catalogUnchanged:
                    asyncio.create_task(
                        self.crud_nodes_catalogs.drop_created_no_report_ttl(
                            node_id=certname,
                            _id=data_decomp["catalog_uuid"],
                        )
                    )
                elif result["report"]["status"] != "unchanged":
                    asyncio.create_task(
                        self.crud_nodes_catalogs.drop_created_no_report_ttl(
                            node_id=certname,
                            _id=data_decomp["catalog_uuid"],
                        )
                    )

        stop_time_ns = time.perf_counter_ns()
        duration_ms = (stop_time_ns - start_time_ns) / 1_000_000
        self.log.info(f"create {command} took {duration_ms:.2f} ms")

        if self.config.app.puppetdb.serverurl:
            asyncio.create_task(
                self.http.post(
                    url=f"{self.config.app.puppetdb.serverurl}/pdb/cmd/v1",
                    params=request.query_params,
                    headers=request.headers,
                    content=body,
                )
            )
        return {}
