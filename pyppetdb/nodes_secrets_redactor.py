import logging
from typing import Any, List

import ahocorasick
from pyppetdb.nodes_data_protector import NodesDataProtector


class NodesSecretsRedactor:
    def __init__(self, log: logging.Logger, protector: NodesDataProtector):
        self.log = log
        self._protector = protector

        self._automaton = ahocorasick.Automaton()
        self._secrets_count = 0

    @property
    def protector(self) -> NodesDataProtector:
        return self._protector

    def encrypt(self, cleartext: str) -> str:
        return self.protector.encrypt_string(cleartext)

    def decrypt(self, ciphertext: str) -> str:
        return self.protector.decrypt_string(ciphertext)

    def add_secret(self, secret: str):
        if not secret:
            return

        self._automaton.add_word(secret, len(secret))
        self._automaton.make_automaton()
        self._secrets_count += 1
        self.log.info(f"Secret added to automaton. Total: {self._secrets_count}")

    def rebuild(self, cleartext_secrets: List[str]):
        new_automaton = ahocorasick.Automaton()
        count = 0
        unique_secrets = {s for s in cleartext_secrets if s}

        for secret in unique_secrets:
            new_automaton.add_word(secret, len(secret))
            count += 1

        if count > 0:
            new_automaton.make_automaton()

        self._automaton = new_automaton
        self._secrets_count = count
        self.log.info(f"Aho-Corasick automaton rebuilt with {count} secrets")

    def _redact_string(self, text: str) -> str:
        if not text or self._secrets_count == 0:
            return text

        matches = []
        for end_index, length in self._automaton.iter(text):
            start_index = end_index - length + 1
            matches.append((start_index, end_index))

        if not matches:
            return text

        matches.sort()
        merged_matches = []
        curr_start, curr_end = matches[0]
        for next_start, next_end in matches[1:]:
            if next_start <= curr_end:
                curr_end = max(curr_end, next_end)
            else:
                merged_matches.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged_matches.append((curr_start, curr_end))

        result = []
        last_index = 0
        for start, end in merged_matches:
            result.append(text[last_index:start])
            result.append("XXXXX")
            last_index = end + 1
        result.append(text[last_index:])

        return "".join(result)

    def redact(self, data: Any) -> Any:
        if self._secrets_count == 0:
            return data

        if isinstance(data, str):
            return self._redact_string(data)

        elif isinstance(data, dict):
            return {
                self._redact_string(str(k)): self.redact(v) for k, v in data.items()
            }

        elif isinstance(data, list):
            return [self.redact(item) for item in data]

        elif isinstance(data, tuple):
            return tuple(self.redact(item) for item in data)

        return data
