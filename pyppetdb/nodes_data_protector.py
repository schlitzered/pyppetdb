import base64
import hashlib
import json
import logging
import zlib
from typing import Any

from cryptography.fernet import Fernet


class NodesDataProtector:
    def __init__(self, app_secret_key: str, log: logging.Logger):
        self.log = log
        self._fernet = self._derive_fernet(app_secret_key)

    @staticmethod
    def _derive_fernet(key: str) -> Fernet:
        digest = hashlib.sha256(key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypt_string(self, cleartext: str) -> str:
        return self._fernet.encrypt(cleartext.encode()).decode()

    def decrypt_string(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    def encrypt_obj(self, data: Any) -> bytes:
        serialized = json.dumps(data, separators=(",", ":")).encode()
        compressed = zlib.compress(serialized)
        return self._fernet.encrypt(compressed)

    def decrypt_obj(self, encrypted_data: bytes) -> Any:
        try:
            decrypted = self._fernet.decrypt(encrypted_data)
            decompressed = zlib.decompress(decrypted)
            return json.loads(decompressed.decode())
        except Exception as e:
            self.log.error(f"Failed to decrypt/decompress data: {e}")
            raise
