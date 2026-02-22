KEY_MODEL_STATIC_PREFIX = "static:"
KEY_MODEL_DYNAMIC_PREFIX = "dynamic:"


def split_key_model_id(model_id: str) -> tuple[str, str]:
    if model_id.startswith(KEY_MODEL_STATIC_PREFIX):
        return KEY_MODEL_STATIC_PREFIX, model_id[len(KEY_MODEL_STATIC_PREFIX) :]
    if model_id.startswith(KEY_MODEL_DYNAMIC_PREFIX):
        return KEY_MODEL_DYNAMIC_PREFIX, model_id[len(KEY_MODEL_DYNAMIC_PREFIX) :]
    return KEY_MODEL_STATIC_PREFIX, model_id


def prefixed_key_model_id(prefix: str, model_id: str) -> str:
    return f"{prefix}{model_id}"
