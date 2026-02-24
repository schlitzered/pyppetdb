import typing

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

log_levels = typing.Literal[
    "CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"
]


class ConfigAppFacts(BaseModel):
    index: typing.Optional[typing.List[str]] = None


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
    serverurl: typing.Optional[str] = None
    authMtls: typing.Optional[bool] = False
    authSecret: typing.Optional[bool] = True
    ssl: typing.Optional[ConfigAppSSL] = None


class ConfigAppPuppetdb(BaseModel):
    enable: bool = True
    port: int = 8002
    host: str = "127.0.0.1"
    serverurl: typing.Optional[str] = None
    ssl: typing.Optional[ConfigAppSSL] = None


class ConfigApp(BaseModel):
    main: ConfigAppMain = ConfigAppMain()
    puppet: ConfigAppPuppet = ConfigAppPuppet()
    puppetdb: ConfigAppPuppetdb = ConfigAppPuppetdb()
    loglevel: log_levels = "INFO"
    secretkey: str = "secret"


class ConfigLdap(BaseModel):
    url: typing.Optional[str] = None
    basedn: typing.Optional[str] = None
    binddn: typing.Optional[str] = None
    password: typing.Optional[str] = None
    userpattern: typing.Optional[str] = None


class ConfigMongodb(BaseModel):
    url: str = "mongodb://localhost:27017"
    database: str = "pyppetdb"
    placement: typing.Optional[str] = "default"


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


class Config(BaseSettings):
    app: ConfigApp = ConfigApp()
    hiera: ConfigHiera = ConfigHiera()
    ldap: ConfigLdap = ConfigLdap()
    mongodb: ConfigMongodb = ConfigMongodb()
    oauth: typing.Optional[dict[str, ConfigOAuth]] = None
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")
