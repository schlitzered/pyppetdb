# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import MagicMock, patch
from pyppetdb.ca.protocol import ClientCertProtocol


class TestClientCertProtocol(unittest.IsolatedAsyncioTestCase):
    @patch("pyppetdb.ca.protocol.H11Protocol.__init__", return_value=None)
    async def test_connection_made(self, mock_init):
        # 1. Create Mock Transport and SSL Object
        mock_transport = MagicMock()
        mock_ssl_object = MagicMock()
        mock_cert_dict = {"subject": "test_cert"}
        mock_ssl_object.getpeercert.return_value = mock_cert_dict

        def get_extra_info(info):
            if info == "ssl_object":
                return mock_ssl_object
            return None

        mock_transport.get_extra_info.side_effect = get_extra_info

        # 2. Instantiate Protocol
        with patch("pyppetdb.ca.protocol.H11Protocol.connection_made"):
            protocol = ClientCertProtocol()
            protocol.connection_made(mock_transport)
            self.assertEqual(protocol._peer_cert_dict, mock_cert_dict)

    @patch("pyppetdb.ca.protocol.H11Protocol.__init__", return_value=None)
    async def test_handle_events(self, mock_init):
        protocol = ClientCertProtocol()
        protocol._peer_cert_dict = {"subject": "test_cert"}
        # scope is normally populated by uvicorn/h11_impl before/during handle_events
        protocol.scope = {"type": "http"}

        with patch("pyppetdb.ca.protocol.H11Protocol.handle_events"):
            protocol.handle_events()
            self.assertEqual(
                protocol.scope["client_cert_dict"], {"subject": "test_cert"}
            )
