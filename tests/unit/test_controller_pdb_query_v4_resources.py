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
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()

        self.mock_config.app.puppetdb.serverurl = "http://puppetdb"
        self.mock_config.app.puppetdb.ssl = None

        self.controller = ControllerPdbQueryV4Resources(
            self.log, self.mock_config, self.mock_auth_cert
        )

    async def test_get(self):
        mock_request = MagicMock()
        mock_request.query_params = {"query": '["=", "type", "Class"]'}
        mock_request.headers = {}

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"certname": "node1", "type": "Class", "title": "Main"}
        ]

        # We need to mock the http property or the AsyncClient it returns
        with patch.object(
            ControllerPdbQueryV4Resources, "http", new_callable=PropertyMock
        ) as mock_http_prop:
            mock_http_client = AsyncMock(spec=httpx.AsyncClient)
            mock_http_prop.return_value = mock_http_client
            mock_http_client.get.return_value = mock_response

            result = await self.controller.get(mock_request)

        self.assertEqual(
            result, [{"certname": "node1", "type": "Class", "title": "Main"}]
        )
        mock_http_client.get.assert_called_once()

    async def test_get_no_server_url(self):
        self.mock_config.app.puppetdb.serverurl = None
        mock_request = MagicMock()

        result = await self.controller.get(mock_request)
        self.assertEqual(result, [])
