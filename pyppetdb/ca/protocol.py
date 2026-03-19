import asyncio
from typing import Any
from uvicorn.protocols.http.h11_impl import H11Protocol

class ClientCertProtocol(H11Protocol):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._peer_cert_dict = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)
        
        ssl_object = transport.get_extra_info("ssl_object")
        self._peer_cert_dict = None

        if ssl_object:
            self._peer_cert_dict = ssl_object.getpeercert()

    def handle_events(self) -> None:
        super().handle_events()
        if self.scope and isinstance(self.scope, dict):
            self.scope["client_cert_dict"] = self._peer_cert_dict
