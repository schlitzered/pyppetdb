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
from typing import Callable
from typing import Mapping
from typing import Optional

from pyppetdb.errors import MissingSecretReference
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation
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


def resolve_string(
    text: Optional[str], secret_map: Mapping[str, str]
) -> Optional[str]:
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


SECRET_FIELDS = ("password", "body_template", "client_key")


def map_secret_fields(
    check: CAHTTPValidation, func: Callable[[str], str]
) -> CAHTTPValidation:
    mapped = check.model_copy(deep=True)
    for name in SECRET_FIELDS:
        value = getattr(mapped, name)
        if value:
            setattr(mapped, name, func(value))
    for header in mapped.headers or []:
        if header.value:
            header.value = func(header.value)
    return mapped


def find_check_references(check: CAHTTPValidation) -> set[str]:
    refs: set[str] = set()

    def collect(value: str) -> str:
        refs.update(find_references(value))
        return value

    map_secret_fields(check, collect)
    return refs


def resolve_check(
    check: CAHTTPValidation, secret_map: Mapping[str, str]
) -> CAHTTPValidation:
    return map_secret_fields(check, lambda value: resolve_string(value, secret_map))


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


async def validate_secret_references(config: CAValidationConfig, crud_secrets) -> None:
    if not config:
        return

    url_refs = extract_url_references(config)
    if url_refs:
        raise QueryParamValidationError(
            msg=(
                "secret references are not allowed in 'url' "
                f"(found: {', '.join(sorted(url_refs))})"
            )
        )

    if config.san_validation and config.san_validation.http_checks:
        for check in config.san_validation.http_checks:
            if check.password and not find_references(check.password):
                raise QueryParamValidationError(
                    msg=(
                        "basic-auth 'password' must reference a secret "
                        "(e.g. $secrets[MY_SECRET]); literal passwords are not "
                        "allowed"
                    )
                )
            if check.client_key and not find_references(check.client_key):
                raise QueryParamValidationError(
                    msg=(
                        "'client_key' must reference a secret "
                        "(e.g. $secrets[MY_SECRET]); inline client keys are not "
                        "allowed"
                    )
                )

    refs = extract_references(config)
    if refs:
        existing = await crud_secrets.existing_ids(refs)
        missing = sorted(refs - existing)
        if missing:
            raise QueryParamValidationError(
                msg=f"unknown secret references: {', '.join(missing)}"
            )
