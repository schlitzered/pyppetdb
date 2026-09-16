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

import typing
import json

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log_levels = typing.Literal[
    "CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"
]


class ConfigAppFacts(BaseModel):
    index: typing.Optional[typing.List[str]] = None
    indexMaxValueLen: int = 256
    indexDepth: int = 3
    indexDeny: typing.List[str] = []

    @field_validator("index", "indexDeny", mode="before")
    @classmethod
    def parse_index(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class ConfigAppSSL(BaseModel):
    ca: typing.Optional[str] = None
    cert: str
    key: str


class ConfigAppStoreHistory(BaseModel):
    catalog: typing.Optional[bool] = True
    catalogUnchanged: typing.Optional[bool] = False
    catalogNoReportTtl: typing.Optional[int] = 3600
    ttl: typing.Optional[int] = 7776000


class ConfigAppHiera(BaseModel):
    keyModels: typing.Optional[typing.List[str]] = None

    @field_validator("keyModels", mode="before")
    @classmethod
    def parse_key_models(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class ConfigAppMain(BaseModel):
    enable: bool = True
    facts: ConfigAppFacts = ConfigAppFacts()
    hiera: ConfigAppHiera = ConfigAppHiera()
    host: str = "0.0.0.0"
    port: int = 8000
    ssl: typing.Optional[ConfigAppSSL] = None
    storeHistory: ConfigAppStoreHistory = ConfigAppStoreHistory()
    interApiIdleTimeout: int = 300


class ConfigAppPuppet(BaseModel):
    enable: bool = True
    catalogCache: typing.Optional[bool] = True
    catalogCacheFacts: typing.Optional[list[str]] = []
    catalogCacheTTL: typing.Optional[int] = 86400
    serverurl: typing.Optional[str] = None
    timeout: int = 60
    authSecret: typing.Optional[bool] = True
    trustedCns: typing.Optional[list[str]] = []

    @field_validator("catalogCacheFacts", mode="before")
    @classmethod
    def parse_catalog_cache_facts(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @field_validator("trustedCns", mode="before")
    @classmethod
    def parse_trusted_cns(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


query_sources = typing.Literal["internal", "upstream"]


class ConfigAppPuppetdb(BaseModel):
    enable: bool = True
    serverurl: typing.Optional[str] = None
    timeout: int = 60
    trustedCns: typing.Optional[list[str]] = []
    querySource: query_sources = "internal"
    resourceQueryInternal: bool = True
    writeQueueSize: int = 500
    writeQueueWorkers: int = 32
    writeQueueDrainTimeout: float = 30.0
    writeQueueWaitTimeout: float = 30.0
    maxQueryDepth: int = 50
    maxSubqueryDepth: int = 3
    queryTimeout: int = 600
    queryTimeoutMax: int = 0
    maxPageSize: int = 10000

    @field_validator("trustedCns", mode="before")
    @classmethod
    def parse_trusted_cns(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @model_validator(mode="after")
    def validate_query_source(self):
        if self.querySource == "upstream" and not self.serverurl:
            raise ValueError(
                "app_puppetdb_querySource 'upstream' requires app_puppetdb_serverurl"
            )
        return self

    def query_upstream(self, entity: typing.Optional[str] = None) -> bool:
        if self.querySource == "upstream":
            return True
        if entity == "resources" and not self.resourceQueryInternal:
            return bool(self.serverurl)
        return False


class ConfigApp(BaseModel):
    main: ConfigAppMain = ConfigAppMain()
    puppet: ConfigAppPuppet = ConfigAppPuppet()
    puppetdb: ConfigAppPuppetdb = ConfigAppPuppetdb()
    loglevel: log_levels = "INFO"
    logstruct: bool = False
    secretkey: str
    wssalt: str = "ws-auth"


class ConfigLdap(BaseModel):
    url: typing.Optional[str] = None
    basedn: typing.Optional[str] = None
    binddn: typing.Optional[str] = None
    password: typing.Optional[str] = None
    userpattern: typing.Optional[str] = None


class ConfigMongodb(BaseModel):
    url: str = "mongodb://localhost:27017"
    database: str = "pyppetdb"
    placementFacts: typing.List[str] = []

    @field_validator("placementFacts", mode="before")
    @classmethod
    def parse_placement_facts(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class ConfigOAuthClient(BaseModel):
    id: str
    secret: str


class ConfigOAuthUrl(BaseModel):
    authorize: str
    accesstoken: str
    userinfo: typing.Optional["str"] = None


class ConfigOAuth(BaseModel):
    override: bool = False
    scope: str
    type: str
    client: ConfigOAuthClient
    url: ConfigOAuthUrl


class ConfigCA(BaseModel):
    enableCrlRefresh: bool = True
    crlRefreshInterval: int = 3600
    crlValidityDays: int = 30
    autoSign: bool = False
    autoSignNodeIfExists: bool = False
    certificateValidityDays: int = 365
    concurrentWorkers: int = 5
    verifyCertificateRegistration: bool = True
    verifyCertificateRegistrationCacheTtl: int = 300
    verifyCertificateRegistrationCacheMaxsize: int = 1024


class ConfigJobs(BaseModel):
    maxNodesPerJob: int = 1000
    expireSeconds: int = 3600


class Config(BaseSettings):
    app: ConfigApp
    ca: ConfigCA = ConfigCA()
    jobs: ConfigJobs = ConfigJobs()
    ldap: ConfigLdap = ConfigLdap()
    mongodb: ConfigMongodb = ConfigMongodb()
    oauth: typing.Optional[dict[str, ConfigOAuth]] = None
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")
