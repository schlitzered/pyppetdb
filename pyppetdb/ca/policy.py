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

import logging
import re
from typing import List
from typing import Optional

from pyppetdb.model.ca_validation import CASigningPolicy
from pyppetdb.model.ca_validation import CAValidationConfig


def allowed_extensions(
    ca_config: CAValidationConfig, space_config: CAValidationConfig
) -> Optional[List[str]]:
    configured = [
        set(config.allowed_extensions)
        for config in (ca_config, space_config)
        if config.allowed_extensions is not None
    ]
    if not configured:
        return None
    return sorted(set.intersection(*configured))


def injected_sans(
    log: logging.Logger, cn: str, configs: List[CAValidationConfig]
) -> List[str]:
    injected = set()
    for config in configs:
        for rule in config.san_injection or []:
            match = re.fullmatch(rule.pattern, cn)
            if not match:
                continue
            groups = [match.group(0)] + list(match.groups())
            for template in rule.templates:
                try:
                    injected.add(template.format(*groups, **match.groupdict()))
                except Exception as err:
                    log.error(
                        f"Failed to format SAN injection template '{template}': {err}"
                    )
    return sorted(injected)


def honor_requested_sans(
    ca_config: CAValidationConfig, space_config: CAValidationConfig
) -> bool:
    return bool(ca_config.san_validation) or bool(space_config.san_validation)


def signing_policy(
    log: logging.Logger,
    cn: str,
    ca_config: CAValidationConfig,
    space_config: CAValidationConfig,
) -> CASigningPolicy:
    if space_config.key_usages is not None:
        key_usages = space_config.get_key_usage_kwargs()
    else:
        key_usages = ca_config.get_key_usage_kwargs()
    return CASigningPolicy(
        allowed_extensions=allowed_extensions(ca_config, space_config),
        key_usages=key_usages,
        extended_key_usages=list(
            space_config.extended_key_usages or ca_config.extended_key_usages or []
        ),
        injected_sans=injected_sans(log, cn, [ca_config, space_config]),
        honor_requested_sans=honor_requested_sans(ca_config, space_config),
    )
