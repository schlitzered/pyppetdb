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

from typing import List
from typing import Optional
from typing import Literal
from typing import Any
from pydantic import BaseModel
from pydantic import model_validator


class CAHTTPHeader(BaseModel):
    name: str
    value: str
    secret: bool = False


class CAHTTPValidation(BaseModel):
    url: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "GET"
    headers: Optional[List[CAHTTPHeader]] = None
    body_template: Optional[str] = None
    verify_ssl: bool = True
    ca_cert: Optional[str] = None
    client_cert: Optional[str] = None
    client_key: Optional[str] = None
    timeout_seconds: int = 5
    basic_auth_enabled: bool = False
    username: Optional[str] = None
    password: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_headers(cls, data: Any) -> Any:
        if isinstance(data, dict) and "headers" in data:
            headers = data["headers"]
            if isinstance(headers, dict):
                # Convert old Dict[str, str] to List[CAHTTPHeader]
                data["headers"] = [
                    {"name": k, "value": v, "secret": False} for k, v in headers.items()
                ]
        return data


class CAScriptValidation(BaseModel):
    script_path: str
    timeout_seconds: int = 5


class CASANValidation(BaseModel):
    max_san_count: int = 10
    regex_list: Optional[List[str]] = None
    http_checks: Optional[List[CAHTTPValidation]] = None
    script_checks: Optional[List[CAScriptValidation]] = None


class CASANInjection(BaseModel):
    pattern: str
    templates: List[str]


class CAValidationConfig(BaseModel):
    enforce_rfc1123: bool = True
    allowed_extensions: Optional[List[str]] = None
    san_validation: Optional[CASANValidation] = None
    san_injection: Optional[List[CASANInjection]] = None
    key_usages: Optional[List[str]] = [
        "digital_signature",
        "key_encipherment",
    ]
    extended_key_usages: Optional[List[str]] = [
        "SERVER_AUTH",
        "CLIENT_AUTH",
    ]

    def get_key_usage_kwargs(self) -> dict[str, bool]:
        usage_kwargs = {
            "digital_signature": False,
            "content_commitment": False,
            "key_encipherment": False,
            "data_encipherment": False,
            "key_agreement": False,
            "key_cert_sign": False,
            "crl_sign": False,
            "encipher_only": False,
            "decipher_only": False,
        }
        if self.key_usages:
            for usage in self.key_usages:
                if usage in usage_kwargs:
                    usage_kwargs[usage] = True
        return usage_kwargs
