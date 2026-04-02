import typing
from pyppetdb.config import Config


def calculate_placement(
    config: Config, facts: typing.Dict[str, typing.Any]
) -> typing.Dict[str, str]:
    placement = {}
    for fact in config.mongodb.placementFacts:
        value = facts.get(fact, "unknown")
        if not isinstance(value, str):
            value = str(value)
        placement[fact] = value
    return placement
