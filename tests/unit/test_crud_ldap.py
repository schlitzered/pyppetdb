import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
import asyncio
import bonsai.errors
from pyppetdb.crud.ldap import CrudLdap
from pyppetdb.errors import AuthenticationError, LdapInvalidDN, LdapResourceNotFound


class TestCrudLdapUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_pool = MagicMock()
        self.mock_pool.max_connection = 10
        self.crud = CrudLdap(
            self.log,
            ldap_base_dn="dc=ex,dc=com",
            ldap_bind_dn="cn=admin",
            ldap_pool=self.mock_pool,
            ldap_url="ldap://localhost",
            ldap_user_pattern="{}@ex.com",
        )

    async def test_ldap_search_success(self):
        mock_conn = AsyncMock()
        mock_conn.search.return_value = ["res1"]
        self.mock_pool.get = AsyncMock(return_value=mock_conn)
        self.mock_pool.put = AsyncMock()

        res = await self.crud._ldap_search("base", 1, "query")
        self.assertEqual(res, ["res1"])
        self.mock_pool.get.assert_called_once()
        self.mock_pool.put.assert_called_once_with(mock_conn)

    async def test_get_login(self):
        self.crud._ldap_search = AsyncMock(
            return_value=[{"sAMAccountName": ["user1_login"]}]
        )
        login = await self.crud.get_login("cn=user1,dc=ex,dc=com")
        self.assertEqual(login, ["user1_login"])

    async def test_get_logins_from_group_success(self):
        self.crud._ldap_search = AsyncMock(
            return_value=[{"member": ["cn=u1,dc=ex", "cn=u2,dc=ex"]}]
        )
        self.crud.get_login = AsyncMock(side_effect=[["u1_login"], ["u2_login"]])

        logins = await self.crud.get_logins_from_group("cn=group1,dc=ex")
        self.assertIn("u1_login", logins)
        self.assertIn("u2_login", logins)
        self.assertEqual(len(logins), 2)

    async def test_get_logins_from_group_invalid_dn(self):
        with self.assertRaises(LdapInvalidDN):
            await self.crud.get_logins_from_group("invalid_dn")

    async def test_get_logins_from_group_not_found(self):
        self.crud._ldap_search = AsyncMock(return_value=[])
        with self.assertRaises(LdapResourceNotFound):
            await self.crud.get_logins_from_group("cn=g1,dc=ex")

    @patch("bonsai.LDAPClient")
    async def test_check_user_credentials_success(self, mock_client_class):
        mock_client = mock_client_class.return_value
        mock_conn = AsyncMock()
        mock_conn.search.return_value = ["user_obj"]

        # Mocking async context manager
        mock_client.connect.return_value.__aenter__.return_value = mock_conn

        res = await self.crud.check_user_credentials("user1", "pass")
        self.assertEqual(res, "user_obj")
        mock_client.set_credentials.assert_called_with("SIMPLE", "user1@ex.com", "pass")

    @patch("bonsai.LDAPClient")
    async def test_check_user_credentials_failure(self, mock_client_class):
        mock_client = mock_client_class.return_value
        mock_conn = AsyncMock()
        mock_conn.search.side_effect = bonsai.errors.AuthenticationError
        mock_client.connect.return_value.__aenter__.return_value = mock_conn

        with self.assertRaises(AuthenticationError):
            await self.crud.check_user_credentials("user1", "wrong")
