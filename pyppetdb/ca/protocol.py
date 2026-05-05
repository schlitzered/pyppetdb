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

import asyncio
from typing import Any
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol


class ClientCertProtocol(H11Protocol):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._peer_cert_dict = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)
        ssl_object = transport.get_extra_info("ssl_object")
        self._peer_cert_dict = ssl_object.getpeercert() if ssl_object else None

    def handle_events(self) -> None:
        if self.scope and isinstance(self.scope, dict):
            if self._peer_cert_dict and "client_cert_dict" not in self.scope:
                self.scope["client_cert_dict"] = self._peer_cert_dict
        super().handle_events()
        if self.scope and isinstance(self.scope, dict):
            if self._peer_cert_dict and "client_cert_dict" not in self.scope:
                self.scope["client_cert_dict"] = self._peer_cert_dict


class ClientCertWebSocketsProtocol(WebSocketProtocol):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._peer_cert_dict = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)
        ssl_object = transport.get_extra_info("ssl_object")
        self._peer_cert_dict = ssl_object.getpeercert() if ssl_object else None

    async def run_asgi(self) -> None:
        if self.scope and isinstance(self.scope, dict):
            if self._peer_cert_dict and "client_cert_dict" not in self.scope:
                self.scope["client_cert_dict"] = self._peer_cert_dict
        await super().run_asgi()
