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

import ssl

from pyppetdb.config import ConfigAppMain
from pyppetdb.server.protocol import ClientCertProtocol
from pyppetdb.server.protocol import ClientCertWebSocketsProtocol


def uvicorn_settings(main: ConfigAppMain) -> dict:
    tls = main.ssl
    return {
        "host": main.host,
        "port": main.port,
        "log_config": None,
        "ssl_ca_certs": tls.ca if tls else None,
        "ssl_certfile": tls.cert if tls else None,
        "ssl_keyfile": tls.key if tls else None,
        "ssl_cert_reqs": ssl.CERT_OPTIONAL if tls else ssl.CERT_NONE,
        "http": ClientCertProtocol if tls else "auto",
        "ws": ClientCertWebSocketsProtocol if tls else "auto",
        "loop": "uvloop",
    }
