import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.nodes_credentials import ControllerApiV1NodesCredentials
from pyppetdb.model.credentials import CredentialPost

class TestApiV1NodesCredentialsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_creds = MagicMock()
        
        self.controller = ControllerApiV1NodesCredentials(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_credentials=self.mock_crud_creds
        )

    async def test_create_credential(self):
        # Mocking auth
        self.mock_authorize.require_admin = AsyncMock()
        
        # Mocking CRUD
        self.mock_crud_nodes.resource_exists = AsyncMock()
        self.mock_crud_creds.create = AsyncMock()
        
        payload = CredentialPost(description="node-desc")
        mock_request = MagicMock()
        
        await self.controller.create(data=payload, node_id="node1", request=mock_request)
        
        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.resource_exists.assert_called_once_with(_id="node1")
        self.mock_crud_creds.create.assert_called_once_with(owner="node1", payload=payload)

    async def test_delete_credential(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_creds.delete = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.delete(node_id="node1", credential_id="cred1", request=mock_request)
        
        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_creds.delete.assert_called_once_with(_id="cred1", owner="node1")

    async def test_get_credential(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_creds.get = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.get(node_id="node1", credential_id="cred1", request=mock_request, fields=set())
        self.mock_crud_creds.get.assert_called_once()

    async def test_search_credentials(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_creds.search = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.search(
            node_id="node1",
            request=mock_request,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10
        )
        self.mock_crud_creds.search.assert_called_once()

    async def test_update_credential(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_creds.update = AsyncMock()
        
        from pyppetdb.model.credentials import CredentialPut
        payload = CredentialPut(description="new desc")
        mock_request = MagicMock()
        await self.controller.update(node_id="node1", credential_id="cred1", data=payload, request=mock_request, fields=set())
        self.mock_crud_creds.update.assert_called_once()
