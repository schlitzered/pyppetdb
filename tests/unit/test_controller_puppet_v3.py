import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
import json
import asyncio
import httpx
from fastapi import HTTPException
from pyppetdb.controller.puppet.v3.facts import ControllerPuppetV3Facts
from pyppetdb.controller.puppet.v3.node import ControllerPuppetV3Node
from pyppetdb.controller.puppet.v3.report import ControllerPuppetV3Report
from pyppetdb.controller.puppet.v3.file_metadata import ControllerPuppetV3FileMetadata
from pyppetdb.controller.puppet.v3.file_bucket_file import ControllerPuppetV3FileBucketFile

from pyppetdb.controller.puppet.v3.file_content import ControllerPuppetV3FileContent

from pyppetdb.controller.puppet.v3.catalog import ControllerPuppetV3Catalog

class TestControllerPuppetV3Unit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_http = AsyncMock(spec=httpx.AsyncClient)
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_match = AsyncMock()
        self.mock_auth_cert.require_cn = AsyncMock()
        self.mock_crud_catalog_cache = AsyncMock()
        
        self.mock_config.app.puppet.serverurl = "http://puppetmaster"
        self.mock_config.app.puppet.catalogCache = True
        self.mock_config.app.puppet.catalogCacheFacts = ["os.family", "ipaddress"]

    async def test_catalog_post_cached(self):
        controller = ControllerPuppetV3Catalog(
            self.log, self.mock_config, self.mock_http, self.mock_auth_cert, self.mock_crud_catalog_cache
        )
        mock_request = MagicMock()
        self.mock_crud_catalog_cache.get_catalog.return_value = {"name": "node1", "resources": []}
        
        result = await controller.post(mock_request, "node1")
        self.assertEqual(result, {"name": "node1", "resources": []})
        self.mock_crud_catalog_cache.get_catalog.assert_called_once_with(node_id="node1")

    async def test_catalog_post_not_cached(self):
        controller = ControllerPuppetV3Catalog(
            self.log, self.mock_config, self.mock_http, self.mock_auth_cert, self.mock_crud_catalog_cache
        )
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        
        facts_json = json.dumps({"values": {"os": {"family": "RedHat"}, "ipaddress": "1.2.3.4"}})
        mock_request.form = AsyncMock(return_value={"facts": facts_json})
        
        self.mock_crud_catalog_cache.get_catalog.return_value = None
        
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"name": "node1", "resources": []}
        self.mock_http.post.return_value = mock_response
        
        result = await controller.post(mock_request, "node1")
        self.assertEqual(result, {"name": "node1", "resources": []})
        
        # Check if facts were filtered correctly before caching (background task)
        # We need to wait a bit for the background task to be scheduled/run
        await asyncio.sleep(0.1)
        self.mock_crud_catalog_cache.upsert.assert_called_once()
        args, kwargs = self.mock_crud_catalog_cache.upsert.call_args
        self.assertEqual(kwargs["facts"], {"os.family": "RedHat", "ipaddress": "1.2.3.4"})

    async def test_catalog_get_not_allowed(self):
        controller = ControllerPuppetV3Catalog(
            self.log, self.mock_config, self.mock_http, self.mock_auth_cert, self.mock_crud_catalog_cache
        )
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.get(mock_request, "node1")
        self.assertEqual(cm.exception.status_code, 405)

    async def test_file_content_get_module(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        
        with patch("pyppetdb.controller.puppet.v3.file_content.Path") as mock_path:
            mock_full_path = MagicMock()
            mock_full_path.resolve.return_value = mock_full_path
            mock_full_path.is_file.return_value = True
            mock_full_path.relative_to.return_value = "relative/path"
            
            mock_path.return_value = mock_path
            mock_path.__truediv__.return_value = mock_path
            mock_path.__truediv__.side_effect = lambda x: mock_full_path if x == "motd" else mock_path
            
            with patch("pyppetdb.controller.puppet.v3.file_content.FileResponse") as mock_file_response:
                result = await controller.get(mock_request, "modules/testmod", "motd")
                self.assertIsInstance(result, MagicMock)

    async def test_file_content_get_tasks(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        
        with patch("pyppetdb.controller.puppet.v3.file_content.Path") as mock_path:
            mock_full_path = MagicMock()
            mock_full_path.resolve.return_value = mock_full_path
            mock_full_path.is_file.return_value = True
            mock_full_path.relative_to.return_value = "relative/path"
            
            mock_path.return_value = mock_path
            mock_path.__truediv__.return_value = mock_path
            mock_path.__truediv__.side_effect = lambda x: mock_full_path if x == "init.sh" else mock_path
            
            with patch("pyppetdb.controller.puppet.v3.file_content.FileResponse") as mock_file_response:
                result = await controller.get(mock_request, "tasks/testmod", "init.sh")
                self.assertIsInstance(result, MagicMock)

    async def test_file_content_get_plugins(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        
        with patch("pyppetdb.controller.puppet.v3.file_content.Path") as mock_path:
            mock_env_modules = MagicMock()
            mock_module_dir = MagicMock()
            mock_module_dir.is_dir.return_value = True
            mock_env_modules.iterdir.return_value = [mock_module_dir]
            
            mock_candidate = MagicMock()
            mock_candidate.is_file.return_value = True
            mock_candidate.resolve.return_value = mock_candidate
            mock_candidate.relative_to.return_value = "relative"
            
            # This is tricky because of multiple Path() calls and / operators
            # codedir = Path("/etc/puppetlabs/code") -> mock_path
            # env_modules = codedir / "environments" / environment / "modules" -> mock_env_modules
            
            mock_path.return_value = mock_path
            mock_path.__truediv__.side_effect = lambda x: mock_env_modules if x == "modules" else mock_path
            mock_module_dir.__truediv__.return_value = mock_module_dir
            mock_module_dir.__truediv__.side_effect = lambda x: mock_candidate if x == "my_fact.rb" else mock_module_dir
            
            with patch("pyppetdb.controller.puppet.v3.file_content.FileResponse") as mock_file_response:
                result = await controller.get(mock_request, "plugins", "my_fact.rb")
                self.assertIsInstance(result, MagicMock)

    async def test_file_content_get_pluginfacts(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        
        with patch("pyppetdb.controller.puppet.v3.file_content.Path") as mock_path:
            mock_env_modules = MagicMock()
            mock_module_dir = MagicMock()
            mock_module_dir.is_dir.return_value = True
            mock_env_modules.iterdir.return_value = [mock_module_dir]
            
            mock_candidate = MagicMock()
            mock_candidate.is_file.return_value = True
            mock_candidate.resolve.return_value = mock_candidate
            mock_candidate.relative_to.return_value = "relative"
            
            mock_path.return_value = mock_path
            mock_path.__truediv__.side_effect = lambda x: mock_env_modules if x == "modules" else mock_path
            mock_module_dir.__truediv__.return_value = mock_module_dir
            mock_module_dir.__truediv__.side_effect = lambda x: mock_candidate if x == "my_fact.sh" else mock_module_dir
            
            with patch("pyppetdb.controller.puppet.v3.file_content.FileResponse") as mock_file_response:
                result = await controller.get(mock_request, "pluginfacts", "my_fact.sh")
                self.assertIsInstance(result, MagicMock)

    async def test_file_content_missing_env(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        with self.assertRaises(HTTPException) as cm:
            await controller.get(mock_request, "plugins", "f")
        self.assertEqual(cm.exception.status_code, 400)

    async def test_file_content_unsupported_mount(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        with self.assertRaises(HTTPException) as cm:
            await controller.get(mock_request, "unsupported", "f")
        self.assertEqual(cm.exception.status_code, 400)

    async def test_file_content_traversal(self):
        controller = ControllerPuppetV3FileContent(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {"environment": "prod"}
        
        with patch("pyppetdb.controller.puppet.v3.file_content.Path") as mock_path:
            mock_full_path = MagicMock()
            mock_full_path.resolve.return_value = mock_full_path
            mock_full_path.relative_to.side_effect = ValueError("Traversal")
            
            mock_path.return_value = mock_path
            mock_path.__truediv__.return_value = mock_path
            mock_path.__truediv__.side_effect = lambda x: mock_full_path if x == "motd" else mock_path
            
            with self.assertRaises(HTTPException) as cm:
                await controller.get(mock_request, "modules/m", "motd")
            self.assertEqual(cm.exception.status_code, 403)

    async def test_facts_put(self):
        controller = ControllerPuppetV3Facts(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        facts_data = {
            "values": {"os": "linux"}, 
            "name": "node1", 
            "timestamp": "2026-03-20T10:00:00Z", 
            "expiration": "2026-03-20T11:00:00Z"
        }
        mock_request.body = AsyncMock(return_value=json.dumps(facts_data).encode())
        mock_request.json = AsyncMock(return_value=facts_data)
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        self.mock_http.put.return_value = mock_response
        
        result = await controller.put(mock_request, "node1")
        self.assertEqual(result, {"status": "success"})
        self.mock_http.put.assert_called_once()

    async def test_facts_put_no_server_url(self):
        self.mock_config.app.puppet.serverurl = None
        controller = ControllerPuppetV3Facts(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.put(mock_request, "node1")
        self.assertEqual(cm.exception.status_code, 502)

    async def test_node_get(self):
        controller = ControllerPuppetV3Node(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "node1"}
        self.mock_http.get.return_value = mock_response
        
        result = await controller.get(mock_request, "node1")
        self.assertEqual(result, {"name": "node1"})
        self.mock_http.get.assert_called_once()

    async def test_report_put(self):
        controller = ControllerPuppetV3Report(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b'{"report": "data"}')
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "received"}
        self.mock_http.put.return_value = mock_response
        
        result = await controller.put(mock_request, "node1")
        self.assertEqual(result, {"status": "received"})
        self.mock_http.put.assert_called_once()

    async def test_file_metadata_get_single(self):
        controller = ControllerPuppetV3FileMetadata(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"path": "/etc/motd"}
        self.mock_http.get.return_value = mock_response
        
        result = await controller.get_single(mock_request, "modules", "motd")
        self.assertEqual(result, {"path": "/etc/motd"})
        self.mock_http.get.assert_called_once()

    async def test_file_metadata_get_multiple(self):
        controller = ControllerPuppetV3FileMetadata(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = [{"path": "/etc/motd"}]
        self.mock_http.get.return_value = mock_response
        
        result = await controller.get_multiple(mock_request, "modules", "motd")
        self.assertEqual(result, [{"path": "/etc/motd"}])

    async def test_file_metadata_get_multiple_root(self):
        controller = ControllerPuppetV3FileMetadata(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        
        mock_response = MagicMock()
        mock_response.json.return_value = [{"path": "/etc/motd"}]
        self.mock_http.get.return_value = mock_response
        
        result = await controller.get_multiple_root(mock_request, "modules")
        self.assertEqual(result, [{"path": "/etc/motd"}])

    async def test_file_metadata_get_error(self):
        controller = ControllerPuppetV3FileMetadata(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.headers = {}
        self.mock_http.get.side_effect = httpx.RequestError("Connection failed")
        
        with self.assertRaises(HTTPException) as cm:
            await controller.get_single(mock_request, "modules", "motd")
        self.assertEqual(cm.exception.status_code, 502)

    async def test_file_bucket_file_get_without_path(self):
        controller = ControllerPuppetV3FileBucketFile(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.get_without_path(mock_request, "md5sum")
        self.assertEqual(cm.exception.status_code, 404)

    async def test_file_bucket_file_get_with_path(self):
        controller = ControllerPuppetV3FileBucketFile(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.get_with_path(mock_request, "md5sum", "/path")
        self.assertEqual(cm.exception.status_code, 404)

    async def test_file_bucket_file_put_without_path(self):
        controller = ControllerPuppetV3FileBucketFile(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.put_without_path(mock_request, "md5sum")
        self.assertEqual(cm.exception.status_code, 400)

    async def test_file_bucket_file_put_with_path(self):
        controller = ControllerPuppetV3FileBucketFile(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.put_with_path(mock_request, "md5sum", "/path")
        self.assertEqual(cm.exception.status_code, 400)

    async def test_file_bucket_file_head_without_path(self):
        controller = ControllerPuppetV3FileBucketFile(self.log, self.mock_config, self.mock_http, self.mock_auth_cert)
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await controller.head_without_path(mock_request, "md5sum")
        self.assertEqual(cm.exception.status_code, 404)
