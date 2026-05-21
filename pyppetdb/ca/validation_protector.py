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

from pyppetdb.model.ca_validation import CAValidationConfig
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector


class CAValidationProtector:
    def __init__(self, protector: NodesDataProtector):
        self._protector = protector

    def encrypt_config(self, config: CAValidationConfig) -> CAValidationConfig:
        if (
            not config
            or not config.san_validation
            or not config.san_validation.http_checks
        ):
            return config

        for check in config.san_validation.http_checks:
            if check.username:
                check.username = self._protector.encrypt_string(check.username)
            if check.password:
                check.password = self._protector.encrypt_string(check.password)
            if check.headers:
                for header in check.headers:
                    if header.secret:
                        header.value = self._protector.encrypt_string(header.value)
        return config

    def decrypt_config(self, config: CAValidationConfig) -> CAValidationConfig:
        if (
            not config
            or not config.san_validation
            or not config.san_validation.http_checks
        ):
            return config

        for check in config.san_validation.http_checks:
            if check.username:
                try:
                    check.username = self._protector.decrypt_string(check.username)
                except Exception:
                    pass
            if check.password:
                try:
                    check.password = self._protector.decrypt_string(check.password)
                except Exception:
                    pass
            if check.headers:
                for header in check.headers:
                    if header.secret:
                        try:
                            header.value = self._protector.decrypt_string(header.value)
                        except Exception:
                            pass
        return config

    def mask_config(self, config: CAValidationConfig) -> CAValidationConfig:
        if (
            not config
            or not config.san_validation
            or not config.san_validation.http_checks
        ):
            return config

        for check in config.san_validation.http_checks:
            if check.username:
                check.username = "*****"
            if check.password:
                check.password = "*****"
            if check.headers:
                for header in check.headers:
                    if header.secret:
                        header.value = "*****"
        return config

    def merge_secrets(
        self, new_config: CAValidationConfig, old_config: CAValidationConfig
    ) -> CAValidationConfig:
        if (
            not new_config
            or not new_config.san_validation
            or not new_config.san_validation.http_checks
        ):
            return new_config

        if (
            not old_config
            or not old_config.san_validation
            or not old_config.san_validation.http_checks
        ):
            return new_config

        for i, new_check in enumerate(new_config.san_validation.http_checks):
            # Find a matching check in the old config.
            # We try to match by URL and method first, then by index if it's likely same.
            old_check = None
            if i < len(old_config.san_validation.http_checks):
                c = old_config.san_validation.http_checks[i]
                if c.url == new_check.url and c.method == new_check.method:
                    old_check = c

            if not old_check:
                for c in old_config.san_validation.http_checks:
                    if c.url == new_check.url and c.method == new_check.method:
                        old_check = c
                        break

            if not old_check:
                continue

            if new_check.username == "*****":
                new_check.username = old_check.username
            if new_check.password == "*****":
                new_check.password = old_check.password

            if new_check.headers and old_check.headers:
                old_headers = {h.name: h.value for h in old_check.headers if h.secret}
                for new_header in new_check.headers:
                    if new_header.secret and new_header.value == "*****":
                        if new_header.name in old_headers:
                            new_header.value = old_headers[new_header.name]
        return new_config
