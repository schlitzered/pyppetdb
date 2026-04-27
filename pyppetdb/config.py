import typing
import json

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log_levels = typing.Literal[
    "CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"
]


class ConfigAppFacts(BaseModel):
    index: typing.Optional[typing.List[str]] = None

    @field_validator("index", mode="before")
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


class ConfigAppMain(BaseModel):
    enable: bool = True
    facts: ConfigAppFacts = ConfigAppFacts()
    host: str = "0.0.0.0"
    port: int = 8000
    ssl: typing.Optional[ConfigAppSSL] = None
    storeHistory: ConfigAppStoreHistory = ConfigAppStoreHistory()


class ConfigAppPuppet(BaseModel):
    enable: bool = True
    port: int = 8001
    host: str = "0.0.0.0"
    catalogCache: typing.Optional[bool] = True
    catalogCacheFacts: typing.Optional[list[str]] = []
    catalogCacheTTL: typing.Optional[int] = 86400
    serverurl: typing.Optional[str] = None
    timeout: int = 60
    authSecret: typing.Optional[bool] = True
    ssl: typing.Optional[ConfigAppSSL] = None
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


class ConfigAppPuppetdb(BaseModel):
    enable: bool = True
    port: int = 8002
    host: str = "127.0.0.1"
    serverurl: typing.Optional[str] = None
    timeout: int = 60
    ssl: typing.Optional[ConfigAppSSL] = None
    trustedCns: typing.Optional[list[str]] = []

    @field_validator("trustedCns", mode="before")
    @classmethod
    def parse_trusted_cns(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class ConfigApp(BaseModel):
    main: ConfigAppMain = ConfigAppMain()
    puppet: ConfigAppPuppet = ConfigAppPuppet()
    puppetdb: ConfigAppPuppetdb = ConfigAppPuppetdb()
    loglevel: log_levels = "INFO"
    secretkey: str = "secret"
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


class ConfigHiera(BaseModel):
    enable: bool = True
    plugin: typing.Optional[dict[str, str]] = None


class ConfigCA(BaseModel):
    enableCrlRefresh: bool = True
    autoSign: bool = False
    autoSignNodeIfExists: bool = False
    certificateValidityDays: int = 365
    concurrentWorkers: int = 5


class ConfigJobs(BaseModel):
    maxNodesPerJob: int = 1000
    expireSeconds: int = 3600


class Config(BaseSettings):
    app: ConfigApp = ConfigApp()
    ca: ConfigCA = ConfigCA()
    hiera: ConfigHiera = ConfigHiera()
    jobs: ConfigJobs = ConfigJobs()
    ldap: ConfigLdap = ConfigLdap()
    mongodb: ConfigMongodb = ConfigMongodb()
    oauth: typing.Optional[dict[str, ConfigOAuth]] = None
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")
