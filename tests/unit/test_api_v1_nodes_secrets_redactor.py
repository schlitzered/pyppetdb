import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.nodes_secrets_redactor import (
    ControllerApiV1NodesSecretsRedactor,
)
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorPost


class TestApiV1NodesSecretsRedactorUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud = MagicMock()

        self.controller = ControllerApiV1NodesSecretsRedactor(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes_secrets_redactor=self.mock_crud,
        )

    async def test_create_secret(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud.create = AsyncMock()

        payload = NodesSecretsRedactorPost(value="secret123")
        mock_request = MagicMock()
        await self.controller.create(request=mock_request, payload=payload)

        self.mock_authorize.require_admin.assert_called_once()
        self.mock_crud.create.assert_called_once_with(payload=payload)

    async def test_delete_secret(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, secret_id="sec1")

        self.mock_authorize.require_admin.assert_called_once()
        self.mock_crud.delete.assert_called_once_with(_id="sec1")

    async def test_search_secrets(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request, secret_id=None, page=0, limit=10
        )
        self.mock_crud.search.assert_called_once()
