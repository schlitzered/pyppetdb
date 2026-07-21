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

"""Resolution of ``$secrets[<id>]`` references in CA validation configs.

Secrets live in their own ``ca_secrets`` collection and are referenced from a
CA authority / space ``validation_config`` using a GitHub-Actions-like syntax:

    "Authorization": "Bearer $secrets[GITHUB_TOKEN]"

References may be embedded anywhere inside a string. A literal ``$secrets[...]``
is written by doubling the leading dollar sign: ``$$secrets[FOO]`` resolves to
the literal text ``$secrets[FOO]`` and is *not* treated as a reference.

References are allowed in HTTP-check header values, the basic-auth ``password``,
the ``body_template`` and ``client_key``. They are intentionally *not* allowed
in ``url`` (URLs can end up in logs) or ``username`` (treated as plain text).
"""

import re
from typing import Optional

from pyppetdb.model.ca_validation import CAValidationConfig

# Grammar for a secret id. Kept in sync with CA_SECRET_ID_PATTERN in
# pyppetdb.model.ca_secrets.
_SECRET_ID = r"[A-Za-z0-9_-]+"

# Matches both a real reference ("$secrets[ID]") and an escaped literal
# ("$$secrets[ID]"). Group 1 is the leading dollar run, group 2 the id.
_REF_RE = re.compile(r"(\$\$?)secrets\[(" + _SECRET_ID + r")\]")


class MissingSecretReference(Exception):
    """Raised when a ``$secrets[<id>]`` reference cannot be resolved."""

    def __init__(self, secret_id: str):
        self.secret_id = secret_id
        super().__init__(f"unknown secret reference: {secret_id}")


def find_references(text: Optional[str]) -> set[str]:
    """Return the set of secret ids referenced (non-escaped) in ``text``."""
    refs: set[str] = set()
    if not text:
        return refs
    for match in _REF_RE.finditer(text):
        if match.group(1) == "$":  # a real reference, not an escaped literal
            refs.add(match.group(2))
    return refs


def resolve_string(text: Optional[str], secret_map: dict[str, str]) -> Optional[str]:
    """Substitute every reference in ``text`` with its value from ``secret_map``.

    Escaped literals (``$$secrets[..]``) are unescaped to ``$secrets[..]``.
    Raises :class:`MissingSecretReference` (fail-closed) if a referenced id is
    not present in ``secret_map``.
    """
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
    """The strings of a single HTTP check that may contain secret references."""
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
    """Return every secret id referenced by a single HTTP check."""
    refs: set[str] = set()
    for value in _check_secret_strings(check):
        refs.update(find_references(value))
    return refs


def resolve_check(check, secret_map: dict[str, str]):
    """Return a deep copy of a single HTTP check with references resolved."""
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
    """Return every secret id referenced across a whole validation config."""
    refs: set[str] = set()
    if not config or not config.san_validation or not config.san_validation.http_checks:
        return refs
    for check in config.san_validation.http_checks:
        refs.update(find_check_references(check))
    return refs


def extract_url_references(config: CAValidationConfig) -> set[str]:
    """Return secret ids referenced from ``url`` fields (which are forbidden)."""
    refs: set[str] = set()
    if not config or not config.san_validation or not config.san_validation.http_checks:
        return refs
    for check in config.san_validation.http_checks:
        refs.update(find_references(check.url))
    return refs


def resolve_config(
    config: CAValidationConfig, secret_map: dict[str, str]
) -> CAValidationConfig:
    """Return a deep copy of ``config`` with all secret references resolved.

    The input config is left untouched so cached / stored objects keep their
    reference form. Raises :class:`MissingSecretReference` if any reference is
    unresolved.
    """
    resolved = config.model_copy(deep=True)
    if not resolved.san_validation or not resolved.san_validation.http_checks:
        return resolved
    resolved.san_validation.http_checks = [
        resolve_check(check, secret_map)
        for check in resolved.san_validation.http_checks
    ]
    return resolved
