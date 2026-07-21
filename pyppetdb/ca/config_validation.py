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

"""Save-time validation of secret references in a CA validation config.

Enforces three rules before a validation_config is persisted:

* ``url`` fields must not reference secrets (they can leak into logs).
* the basic-auth ``password`` must be a secret reference, not a literal (we no
  longer encrypt the config at rest, so a literal would be stored in cleartext).
* every referenced secret id must exist in the ``ca_secrets`` collection.
"""

from pyppetdb.ca.secret_resolver import extract_references
from pyppetdb.ca.secret_resolver import extract_url_references
from pyppetdb.ca.secret_resolver import find_references
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAValidationConfig


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
