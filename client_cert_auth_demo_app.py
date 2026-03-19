import ssl
import asyncio
from typing import Any, Dict
from fastapi import FastAPI, Request
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from cryptography import x509

app = FastAPI()

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

@app.get("/who_am_i")
async def who_am_i(request: Request):
    cert_dict = request.scope.get("client_cert_dict")
    subject = {key: value for rdn in cert_dict.get("subject", []) for key, value in rdn}
    return {
        "method": "ssl_dict",
        "subject": subject,
        "raw_dict": cert_dict
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8443,
        ssl_keyfile="certs/server.key",
        ssl_certfile="certs/server.crt",
        ssl_ca_certs="certs/ca.crt",
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        http=ClientCertProtocol,
        log_level="info"
    )
