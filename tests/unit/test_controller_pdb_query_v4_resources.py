import unittest
from unittest.mock import PropertyMock
from unittest.mock import MagicMock, AsyncMock, patch
import logging
import httpx
from pyppetdb.controller.pdb.query.v4.resources import ControllerPdbQueryV4Resources


class TestControllerPdbQueryV4ResourcesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()

        self.mock_config.app.puppetdb.serverurl = "http://puppetdb"
        self.mock_config.app.puppetdb.ssl = None

        self.controller = ControllerPdbQueryV4Resources(
            self.log, self.mock_config, self.mock_crud_nodes, self.mock_auth_cert
        )

    async def test_get_local_translation(self):
        # All queries are now translated locally when resourceQueryInternal is True
        self.mock_config.app.puppetdb.resourceQueryInternal = True
        mock_request = MagicMock()
        mock_request.query_params = {"query": '["=", "type", "File"]'}

        translated = {"catalog.resources_exported.type": "File"}
        self.mock_crud_nodes.translate_resource_query.return_value = translated
        self.mock_crud_nodes.query_exported_resources = AsyncMock(
            return_value=[{"certname": "node1"}]
        )

        result = await self.controller.get(mock_request)

        self.assertEqual(result, [{"certname": "node1"}])
        self.mock_crud_nodes.translate_resource_query.assert_called_once()
        self.mock_crud_nodes.query_exported_resources.assert_called_once_with(
            translated
        )

    async def test_get_internal_unsupported_query(self):
        # When resourceQueryInternal is True and query is unsupported, return [] (no fallback)
        self.mock_config.app.puppetdb.resourceQueryInternal = True
        mock_request = MagicMock()
        mock_request.query_params = {"query": '["=", "unsupported", "val"]'}

        self.mock_crud_nodes.translate_resource_query.return_value = None

        result = await self.controller.get(mock_request)

        self.assertEqual(result, [])
        self.mock_crud_nodes.translate_resource_query.assert_called_once()

    async def test_get_forward_to_puppetdb(self):
        # When resourceQueryInternal is False, it should forward
        self.mock_config.app.puppetdb.resourceQueryInternal = False
        mock_request = MagicMock()
        mock_request.query_params = {"query": '["=", "type", "Class"]'}
        mock_request.headers = {}

        mock_response = MagicMock()
        mock_response.json.return_value = [{"certname": "node1"}]

        with patch.object(
            ControllerPdbQueryV4Resources, "http", new_callable=PropertyMock
        ) as mock_http_prop:
            mock_http_client = AsyncMock(spec=httpx.AsyncClient)
            mock_http_prop.return_value = mock_http_client
            mock_http_client.get.return_value = mock_response

            result = await self.controller.get(mock_request)

        self.assertEqual(result, [{"certname": "node1"}])
        mock_http_client.get.assert_called_once()

    async def test_get_no_query_param(self):
        # If no query param and resourceQueryInternal is True, return []
        self.mock_config.app.puppetdb.resourceQueryInternal = True
        mock_request = MagicMock()
        mock_request.query_params = {}

        result = await self.controller.get(mock_request)
        self.assertEqual(result, [])

    async def test_get_no_server_url(self):
        self.mock_config.app.puppetdb.serverurl = None
        self.mock_crud_nodes.translate_resource_query.return_value = None
        mock_request = MagicMock()
        mock_request.query_params = {}

        result = await self.controller.get(mock_request)
        self.assertEqual(result, [])
