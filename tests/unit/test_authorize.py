import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.authorize import AuthorizePyppetDB
from pyppetdb.errors import AdminError, SessionCredentialError, PermissionError
from pyppetdb.model.users import UserGet
from pyppetdb.model.teams import TeamGet, TeamGetMulti
from pyppetdb.model.common import MetaMulti


class TestAuthorizeUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")

    async def test_authorize_pyppetdb_get_user_session(self):
        mock_groups = MagicMock()
        mock_teams = MagicMock()
        mock_users = MagicMock()
        mock_creds = MagicMock()

        auth = AuthorizePyppetDB(
            self.log, mock_groups, mock_teams, mock_users, mock_creds
        )
        mock_request = MagicMock()
        mock_request.session = {"username": "user1"}

        mock_users.get = AsyncMock(return_value=UserGet(id="user1", admin=False))

        user = await auth.get_user(mock_request)
        self.assertEqual(user.id, "user1")

    async def test_authorize_pyppetdb_get_user_creds(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        mock_request = MagicMock()
        mock_request.session = {}

        auth.get_user_from_credentials = AsyncMock(return_value="user1")
        auth.crud_users.get = AsyncMock(return_value=UserGet(id="user1", admin=True))

        user = await auth.get_user(mock_request)
        self.assertEqual(user.id, "user1")
        self.assertTrue(user.admin)

    async def test_authorize_pyppetdb_get_user_fail(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        mock_request = MagicMock()
        mock_request.session = {}
        auth.get_user_from_credentials = AsyncMock(return_value=None)

        with self.assertRaises(SessionCredentialError):
            await auth.get_user(mock_request)

    async def test_require_admin_success(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        user = UserGet(id="admin", admin=True)
        # Passing user directly
        result = await auth.require_admin(None, user=user)
        self.assertEqual(result, user)

    async def test_require_admin_failure(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        user = UserGet(id="user1", admin=False)
        with self.assertRaises(AdminError):
            await auth.require_admin(None, user=user)

    async def test_get_user_node_groups_admin(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        user = UserGet(id="admin", admin=True)
        groups = await auth.get_user_node_groups(None, user=user)
        self.assertIsNone(groups)

    async def test_get_user_node_groups_regular(self):
        mock_groups = MagicMock()
        mock_teams = MagicMock()
        auth = AuthorizePyppetDB(
            self.log, mock_groups, mock_teams, MagicMock(), MagicMock()
        )
        user = UserGet(id="user1", admin=False)

        mock_teams.search = AsyncMock(
            return_value=TeamGetMulti(
                result=[TeamGet(id="team1")], meta=MetaMulti(result_size=1)
            )
        )
        mock_groups.search = AsyncMock(
            return_value=MagicMock(result=[MagicMock(id="group1")])
        )

        groups = await auth.get_user_node_groups(None, user=user)
        self.assertEqual(groups, ["group1"])

    async def test_require_perm_admin_success(self):
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        user = UserGet(id="admin", admin=True)
        result = await auth.require_perm(None, "ANY:PERM", user=user)
        self.assertEqual(result, user)

    async def test_require_perm_regular_success(self):
        mock_teams = MagicMock()
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), mock_teams, MagicMock(), MagicMock()
        )
        user = UserGet(id="user1", admin=False)

        mock_teams.search = AsyncMock(
            return_value=TeamGetMulti(
                result=[TeamGet(id="team1", permissions=["CA:SPACES:VIEW"])],
                meta=MetaMulti(result_size=1),
            )
        )

        result = await auth.require_perm(None, "CA:SPACES:VIEW", user=user)
        self.assertEqual(result, user)
        # Verify that search was called with both users and permissions filters
        mock_teams.search.assert_called_once_with(
            users="^user1$", permissions="^CA:SPACES:VIEW$", fields=["id"]
        )

    async def test_require_perm_regular_failure(self):
        mock_teams = MagicMock()
        auth = AuthorizePyppetDB(
            self.log, MagicMock(), mock_teams, MagicMock(), MagicMock()
        )
        user = UserGet(id="user1", admin=False)

        mock_teams.search = AsyncMock(
            return_value=TeamGetMulti(result=[], meta=MetaMulti(result_size=0))
        )

        with self.assertRaises(PermissionError):
            await auth.require_perm(None, "CA:SPACES:VIEW", user=user)
        mock_teams.search.assert_called_once_with(
            users="^user1$", permissions="^CA:SPACES:VIEW$", fields=["id"]
        )
