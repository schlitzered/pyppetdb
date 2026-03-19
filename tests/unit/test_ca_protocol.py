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
            self.assertEqual(protocol.scope["client_cert_dict"], {"subject": "test_cert"})
