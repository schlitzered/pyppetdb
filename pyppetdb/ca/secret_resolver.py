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

import re
from typing import Optional

from pyppetdb.errors import MissingSecretReference
from pyppetdb.model.ca_validation import CAValidationConfig

_SECRET_ID = r"[A-Za-z0-9_-]+"

_REF_RE = re.compile(r"(\$\$?)secrets\[(" + _SECRET_ID + r")\]")


def find_references(text: Optional[str]) -> set[str]:
    refs: set[str] = set()
    if not text:
        return refs
    for match in _REF_RE.finditer(text):
        if match.group(1) == "$":
            refs.add(match.group(2))
    return refs


def resolve_string(text: Optional[str], secret_map: dict[str, str]) -> Optional[str]:
    if not text:
        return text

    def _repl(match: re.Match) -> str:
        marker, secret_id = match.group(1), match.group(2)
        if marker == "$$":
            return f"$secrets[{secret_id}]"
        if secret_id not in secret_map:
            raise MissingSecretReference(secret_id)
        return secret_map[secret_id]

    return _REF_RE.sub(_repl, text)


def _check_secret_strings(check) -> list[str]:
    values: list[str] = []
    if check.password:
        values.append(check.password)
    if check.body_template:
        values.append(check.body_template)
    if check.client_key:
        values.append(check.client_key)
    if check.headers:
        for header in check.headers:
            if header.value:
                values.append(header.value)
    return values


def find_check_references(check) -> set[str]:
    refs: set[str] = set()
    for value in _check_secret_strings(check):
        refs.update(find_references(value))
    return refs


def resolve_check(check, secret_map: dict[str, str]):
    resolved = check.model_copy(deep=True)
    if resolved.password:
        resolved.password = resolve_string(resolved.password, secret_map)
    if resolved.body_template:
        resolved.body_template = resolve_string(resolved.body_template, secret_map)
    if resolved.client_key:
        resolved.client_key = resolve_string(resolved.client_key, secret_map)
    if resolved.headers:
        for header in resolved.headers:
            if header.value:
                header.value = resolve_string(header.value, secret_map)
    return resolved


def extract_references(config: CAValidationConfig) -> set[str]:
    refs: set[str] = set()
    if not config or not config.san_validation or not config.san_validation.http_checks:
        return refs
    for check in config.san_validation.http_checks:
        refs.update(find_check_references(check))
    return refs


def extract_url_references(config: CAValidationConfig) -> set[str]:
    refs: set[str] = set()
    if not config or not config.san_validation or not config.san_validation.http_checks:
        return refs
    for check in config.san_validation.http_checks:
        refs.update(find_references(check.url))
    return refs


def resolve_config(
    config: CAValidationConfig, secret_map: dict[str, str]
) -> CAValidationConfig:
    resolved = config.model_copy(deep=True)
    if not resolved.san_validation or not resolved.san_validation.http_checks:
        return resolved
    resolved.san_validation.http_checks = [
        resolve_check(check, secret_map)
        for check in resolved.san_validation.http_checks
    ]
    return resolved
