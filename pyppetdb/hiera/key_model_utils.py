KEY_MODEL_STATIC_PREFIX = "static:"
KEY_MODEL_DYNAMIC_PREFIX = "dynamic:"


def prefixed_key_model_id(prefix: str, model_id: str) -> str:
    return f"{prefix}{model_id}"
