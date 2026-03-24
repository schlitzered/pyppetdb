import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
import httpx
from fastapi import Response
from pyppetdb.controller.puppet.v3.catalog import ControllerPuppetV3Catalog

class TestControllerPuppetV3CatalogUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_http = AsyncMock(spec=httpx.AsyncClient)
        self.mock_cache = MagicMock()
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()
        self.mock_auth_cert.require_cn_match = AsyncMock()
        
        self.mock_config.app.puppet.catalogCache = True
        self.mock_config.app.puppet.serverurl = "http://puppetmaster"
        self.mock_config.app.puppet.catalogCacheFacts = ["osfamily"]
        
        self.controller = ControllerPuppetV3Catalog(
            self.log, self.mock_config, self.mock_http, self.mock_auth_cert, self.mock_cache
        )

    async def test_post_cached(self):
        self.mock_cache.get_catalog = AsyncMock(return_value={"resources": []})
        mock_request = MagicMock()
        
        result = await self.controller.post(mock_request, "node1")
        self.assertEqual(result, {"resources": []})
        self.mock_cache.get_catalog.assert_called_once_with(node_id="node1")

    async def test_post_not_cached_proxy_and_store(self):
        self.mock_cache.get_catalog = AsyncMock(return_value=None)
        self.mock_cache.upsert = AsyncMock()
        
        mock_response_data = {"proxied": "catalog"}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = json.dumps(mock_response_data).encode()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = mock_response_data
        self.mock_http.post.return_value = mock_response
        
        mock_request = MagicMock()
        facts_data = {"values": {"osfamily": "RedHat"}}
        # FastAPI request.form() mock
        mock_request.form = AsyncMock(return_value={"facts": json.dumps(facts_data)})
        mock_request.headers = {}
        mock_request.query_params = {}
        
        # Mock _headers from base class
        with patch.object(self.controller, "_headers", return_value={}):
            result = await self.controller.post(mock_request, "node1")
        
        self.assertIsInstance(result, Response)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(json.loads(result.body), mock_response_data)
        await asyncio.sleep(0.1) # Wait for background task
        self.mock_cache.upsert.assert_called_once()
        call_args = self.mock_cache.upsert.call_args[1]
        self.assertEqual(call_args["facts"], {"osfamily": "RedHat"})

    def test_extract_nested_fact(self):
        facts = {"os": {"family": "RedHat"}}
        self.assertEqual(self.controller._extract_nested_fact(facts, "os.family"), "RedHat")
        self.assertIsNone(self.controller._extract_nested_fact(facts, "os.unknown"))

    def test_filter_facts(self):
        facts = {"osfamily": "RedHat", "other": "val"}
        configured = ["osfamily", "missing"]
        filtered = self.controller._filter_facts(facts, configured)
        self.assertEqual(filtered, {"osfamily": "RedHat"})
