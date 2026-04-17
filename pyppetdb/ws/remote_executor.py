import logging

from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.errors import ClientCertError
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.jobs_definitions import CrudJobsDefinitions
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.controller.api.v1.remote_executor_protocol import RemoteExecutorProtocol
from pyppetdb.ws.manager import WsManager


class WSRemoteExecutor:
    def __init__(
        self,
        log: logging.Logger,
        authorize_client_cert: AuthorizeClientCert,
        crud_nodes: CrudNodes,
        crud_jobs: CrudJobs,
        crud_job_definitions: CrudJobsDefinitions,
        crud_node_jobs: CrudJobsNodeJobs,
        redactor: NodesSecretsRedactor,
        ws_manager: WsManager,
        via: str,
    ):
        self._log = log
        self._authorize_client_cert = authorize_client_cert
        self._crud_nodes = crud_nodes
        self._crud_jobs = crud_jobs
        self._crud_job_definitions = crud_job_definitions
        self._crud_node_jobs = crud_node_jobs
        self._redactor = redactor
        self._ws_manager = ws_manager
        self._via = via

    async def endpoint(
        self,
        websocket: WebSocket,
        node_id: str,
    ):
        try:
            await websocket.accept()
            await self._authorize_client_cert.require_cn_match(
                request=websocket,
                match=node_id,
            )

            await self._crud_nodes.update_remote_agent_status(
                node_id=node_id,
                connected=True,
                via=self._via,
            )

            protocol = RemoteExecutorProtocol(
                log=self._log,
                node_id=node_id,
                websocket=websocket,
                crud_nodes=self._crud_nodes,
                crud_jobs=self._crud_jobs,
                crud_job_definitions=self._crud_job_definitions,
                crud_node_jobs=self._crud_node_jobs,
                redactor=self._redactor,
                manager=self._ws_manager,
            )

            self._ws_manager.register_protocol(
                node_id=node_id,
                protocol=protocol,
            )
            await protocol.run()

        except ClientCertError as e:
            self._log.error(msg=f"WS remote_executor Auth failed: {e.detail}")
            await websocket.close(code=4003)
        except WebSocketDisconnect:
            await self._handle_disconnect(node_id)
        except Exception as e:
            self._log.error(msg=f"WS remote_executor unexpected error: {e}")
            await self._handle_disconnect(node_id)
            await websocket.close(code=4003)

    async def _handle_disconnect(self, node_id: str):
        self._ws_manager.unregister_protocol(node_id=node_id)
        await self._crud_nodes.update_remote_agent_status(
            node_id=node_id,
            connected=False,
            via=None,
        )
