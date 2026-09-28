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


class PuppetDBQueryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def unknown_field(field: str, entity: str, known: list) -> PuppetDBQueryError:
    known_str = ", ".join(sorted(known))
    return PuppetDBQueryError(
        f"'{field}' is not a queryable object for {entity}. "
        f"Known queryable objects are [{known_str}]."
    )


def unknown_entity(entity: str, known: list) -> PuppetDBQueryError:
    known_str = ", ".join(sorted(known))
    return PuppetDBQueryError(
        f"Invalid query entity '{entity}'. Known entities are [{known_str}]."
    )


def unknown_operator(operator) -> PuppetDBQueryError:
    return PuppetDBQueryError(f"{operator!r} is not a valid query term")


def bad_arity(operator: str, expected: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(f"{operator} requires {expected}")


def bad_operand(operator: str, field: str, value, expected: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f"{value!r} is not a valid value for field '{field}'; "
        f"{operator} requires {expected}"
    )


def bad_regex(field: str, value, reason: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f"Invalid regular expression {value!r} for field '{field}': {reason}"
    )


def bad_operator_arity(operator: str, supplied: int) -> PuppetDBQueryError:
    if operator == "not":
        return PuppetDBQueryError(
            f"'{operator}' takes exactly one argument, "
            f"but {supplied} were supplied"
        )
    return PuppetDBQueryError(
        f"'{operator}' takes at least one argument, but none were supplied"
    )


def comparison_not_allowed(field: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f"Query operators >,>=,<,<= are not allowed on field {field}"
    )


def incompatible_numeric(value, field: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f'Argument "{value}" is incompatible with numeric field "{field}".'
    )


def incompatible_types(value, operator: str) -> PuppetDBQueryError:
    return PuppetDBQueryError(
        f'Argument "{value}" and operator "{operator}" have incompatible types.'
    )


def bad_timestamp(value) -> PuppetDBQueryError:
    return PuppetDBQueryError(f"'{value}' is not a valid timestamp value")


def subquery_too_large() -> PuppetDBQueryError:
    return PuppetDBQueryError(
        "the subquery result is too large to be evaluated; narrow the subquery"
    )
