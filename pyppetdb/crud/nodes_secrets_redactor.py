import asyncio
import hashlib
import logging
import typing

import ahocorasick
from motor.motor_asyncio import AsyncIOMotorCollection
import pymongo
import pymongo.errors

from pyppetdb.config import Config
from pyppetdb.crud.common import CrudMongo
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.model.common import DataDelete
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGet
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorGetMulti
from pyppetdb.model.nodes_secrets_redactor import NodesSecretsRedactorPost


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

    def rebuild(self, cleartext_secrets: typing.List[str]):
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

    def redact(self, data: typing.Any) -> typing.Any:
        if self._secrets_count == 0:
            return data

        if isinstance(data, str):
            return self._redact_string(data)

        elif isinstance(data, dict):
            return {
                self._redact_string(str(k)): self.redact(v) for k, v in data.items()
            }

        elif isinstance(data, typing.List):
            return [self.redact(item) for item in data]

        elif isinstance(data, tuple):
            return tuple(self.redact(item) for item in data)

        return data


class CrudNodesSecretsRedactorCache:
    def __init__(
        self,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        redactor: NodesSecretsRedactor,
    ):
        self._coll = coll
        self._log = log
        self._redactor = redactor
        self._cache: typing.Dict[str, str] = {}
        self._initialized = False

    @property
    def coll(self):
        return self._coll

    @property
    def log(self):
        return self._log

    async def _watch_changes(self):
        try:
            pipeline = [
                {
                    "$project": {
                        "fullDocument.id": 1,
                        "fullDocument.value_encrypted": 1,
                        "operationType": 1,
                        "documentKey._id": 1,
                    }
                }
            ]

            async with self.coll.watch(
                full_document="updateLookup",
                pipeline=pipeline,
            ) as change_stream:
                self.log.info(
                    "Change stream watcher started for nodes_secrets_redactor"
                )
                async for change in change_stream:
                    await self._handle_change(change)

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error in nodes_secrets_redactor change stream: {err}")
        except Exception as err:
            self.log.error(
                f"Unexpected error in nodes_secrets_redactor change stream: {err}"
            )

    async def _handle_change(self, change):
        operation = change["operationType"]
        doc_id = change["documentKey"]["_id"]

        if operation in ("insert", "replace", "update"):
            doc = change.get("fullDocument")
            if doc:
                try:
                    clear = self._redactor.decrypt(doc["value_encrypted"])
                    self._cache[doc_id] = clear
                    # Optimize: Just add the new word to the automaton
                    self._redactor.add_secret(clear)
                except Exception:
                    self.log.error(
                        f"Failed to decrypt secret in change stream: {doc_id}"
                    )
            else:
                self.log.warning(f"No fullDocument in {operation} change for {doc_id}")

        elif operation == "delete":
            self._cache.pop(doc_id, None)
            # Must rebuild because we can't remove words from ahocorasick automaton easily
            self._redactor.rebuild(list(self._cache.values()))

        else:
            self.log.warning(f"Unhandled operation type: {operation}")

    async def _load_initial_data(self):
        try:
            cursor = self.coll.find({}, {"id": 1, "_id": 1, "value_encrypted": 1})
            async for doc in cursor:
                doc_id = doc["_id"]
                try:
                    clear = self._redactor.decrypt(doc["value_encrypted"])
                    self._cache[doc_id] = clear
                except Exception:
                    self.log.error(
                        f"Failed to decrypt secret during initial load: {doc_id}"
                    )

            self._redactor.rebuild(list(self._cache.values()))
            self.log.info(
                f"Loaded {len(self._cache)} initial secrets into redaction cache"
            )

        except pymongo.errors.PyMongoError as err:
            self.log.error(f"Error loading initial secrets data: {err}")
            raise

    async def run(self):
        if self._initialized:
            return
        asyncio.create_task(self._watch_changes())
        await self._load_initial_data()
        self._initialized = True


class CrudNodesSecretsRedactor(CrudMongo):
    def __init__(
        self,
        config: Config,
        log: logging.Logger,
        coll: AsyncIOMotorCollection,
        redactor: NodesSecretsRedactor,
    ):
        super(CrudNodesSecretsRedactor, self).__init__(
            config=config, log=log, coll=coll
        )
        self._redactor = redactor
        self._cache = CrudNodesSecretsRedactorCache(
            log=log, coll=coll, redactor=redactor
        )

    @property
    def cache(self):
        return self._cache

    async def index_create(self) -> None:
        await self.coll.create_index([("id", pymongo.ASCENDING)], unique=True)
        await self.cache.run()

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    async def create(
        self, payload: NodesSecretsRedactorPost
    ) -> NodesSecretsRedactorGet:
        encrypted = self._redactor.encrypt(payload.value)
        fingerprint = self._fingerprint(payload.value)
        data = {
            "id": fingerprint,
            "value_encrypted": encrypted,
        }
        result = await self._create(payload=data, fields=["id"])
        return NodesSecretsRedactorGet(**result)

    async def delete(self, _id: str) -> DataDelete:
        query = {"id": _id}
        await self._delete(query=query)
        return DataDelete()

    async def search(
        self,
        _id: typing.Optional[str] = None,
        page: typing.Optional[int] = None,
        limit: typing.Optional[int] = None,
    ) -> NodesSecretsRedactorGetMulti:
        query = {}
        self._filter_re(query, "id", _id)
        result = await self._search(
            query=query,
            fields=["id"],
            page=page,
            limit=limit,
        )
        return NodesSecretsRedactorGetMulti(**result)
