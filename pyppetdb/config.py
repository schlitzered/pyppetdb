import typing

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

log_levels = typing.Literal[
    "CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"
]


class ConfigAppFacts(BaseModel):
    index: typing.Optional[typing.List[str]] = None


class ConfigAppPuppetDB(BaseModel):
    cert: str
    key: str
    ca: str
    serverurl: str


class ConfigAppSSL(BaseModel):
    cert: str
    key: str


class ConfigAppStoreHistory(BaseModel):
    catalog: typing.Optional[bool] = True
    catalogUnchanged: typing.Optional[bool] = False
    catalogNoReportTtl: typing.Optional[int] = 3600
    ttl: typing.Optional[int] = 7776000


class ConfigApp(BaseModel):
    facts: ConfigAppFacts = ConfigAppFacts()
    loglevel: log_levels = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    puppetdb: typing.Optional[ConfigAppPuppetDB] = None
    secretkey: str = "secret"
    ssl: typing.Optional[ConfigAppSSL] = None
    storeHistory: ConfigAppStoreHistory = ConfigAppStoreHistory()


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


class Config(BaseSettings):
    app: ConfigApp = ConfigApp()
    ldap: ConfigLdap = ConfigLdap()
    mongodb: ConfigMongodb = ConfigMongodb()
    oauth: typing.Optional[dict[str, ConfigOAuth]] = None
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")
