import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.authenticate import ControllerApiV1Authenticate
from pyppetdb.model.authenticate import AuthenticatePost

class TestApiV1AuthenticateUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_users = MagicMock()
        self.mock_http = MagicMock()
        
        self.controller = ControllerApiV1Authenticate(
            log=self.log,
            authorize=self.mock_authorize,
            crud_users=self.mock_crud_users,
            http=self.mock_http
        )

    async def test_get_authenticated_user(self):
        mock_user = MagicMock()
        mock_user.id = "user1"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        
        mock_request = MagicMock()
        result = await self.controller.get(request=mock_request)
        
        self.assertEqual(result["user"], "user1")
        self.mock_authorize.get_user.assert_called_once_with(request=mock_request)

    async def test_create_session(self):
        self.mock_crud_users.check_credentials = AsyncMock(return_value="user1")
        
        mock_request = MagicMock()
        mock_request.session = {}
        
        data = AuthenticatePost(user="user1", password="password123")
        result = await self.controller.create(data=data, request=mock_request)
        
        self.assertEqual(result["user"], "user1")
        self.assertEqual(mock_request.session["username"], "user1")
        self.mock_crud_users.check_credentials.assert_called_once()

    async def test_delete_session(self):
        mock_request = MagicMock()
        mock_request.session = MagicMock(spec=dict)
        
        await self.controller.delete(request=mock_request)
        mock_request.session.clear.assert_called_once()
