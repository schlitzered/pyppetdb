# Configuration Reference

pyppetdb is configured via environment variables or a `.env` file (placed in the process working
directory). Configuration is powered by Pydantic Settings.

## Conventions

* **Nested delimiter:** settings map to a nested model using `_` as the delimiter, e.g.
  `app_main_port` sets `app.main.port`.
* **List / JSON values:** list-typed settings are provided as a JSON string, e.g.
  `app_main_facts_index=["role","stage"]`.
* **Booleans:** use `true` / `false`.
* **Required values:** `app_secretkey` has **no default** and must be set, otherwise the process
  will not start.

---

## Global (`app_`)

| Variable | Default | Description |
|----------|---------|-------------|
| `app_secretkey` | *(required)* | Secret key for session cookies and cryptographic operations. **No default — must be set.** |
| `app_wssalt` | `ws-auth` | Salt used for inter-instance/agent WebSocket authentication. |
| `app_loglevel` | `INFO` | Log level: `CRITICAL`, `FATAL`, `ERROR`, `WARN`, `WARNING`, `INFO`, `DEBUG`. |
| `app_logstruct` | `false` | Emit structured JSON logs (via structlog) instead of plain text. |

## Management API (`app_main_`)

A pyppetdb process always binds on the `app_main_host` / `app_main_port` pair and uses the
`app_main_ssl_*` TLS configuration — regardless of which router groups are enabled.

| Variable | Default | Description |
|----------|---------|-------------|
| `app_main_enable` | `true` | Enable the management API router group (`/api`, `/oauth`). |
| `app_main_host` | `0.0.0.0` | Bind address for this process. |
| `app_main_port` | `8000` | Bind port for this process. |
| `app_main_ssl_cert` | *(unset)* | Path to the server certificate (PEM). Required to enable TLS. |
| `app_main_ssl_key` | *(unset)* | Path to the server private key (PEM). Required to enable TLS. |
| `app_main_ssl_ca` | *(unset)* | Path to the CA bundle used to validate client certificates (enables mTLS). |
| `app_main_facts_index` | *(unset)* | JSON list of facts to index in the database for faster searching. |
| `app_main_hiera_keyModels` | *(unset)* | JSON list of import paths for **static** Hiera key model plugins to register at startup. |
| `app_main_interApiIdleTimeout` | `300` | Idle timeout (seconds) for the inter-instance WebSocket mesh. |

!!! note "TLS is all-or-nothing per process"
    `app_main_ssl_cert` and `app_main_ssl_key` must be provided together to enable TLS. When TLS
    is enabled, client certificates are requested (`CERT_OPTIONAL`); provide `app_main_ssl_ca` so
    Puppet agent / PuppetDB mTLS can be validated.

### History storage (`app_main_storeHistory_`)

Controls how historical catalogs/reports are retained.

| Variable | Default | Description |
|----------|---------|-------------|
| `app_main_storeHistory_catalog` | `true` | Store historical catalogs. |
| `app_main_storeHistory_catalogUnchanged` | `false` | Also store catalogs that did not change. |
| `app_main_storeHistory_catalogNoReportTtl` | `3600` | TTL (seconds) for a stored catalog that never received a matching report. |
| `app_main_storeHistory_ttl` | `7776000` | TTL (seconds) for stored history (default 90 days). |

## Puppet Proxy (`app_puppet_`)

Serves `/puppet` and `/puppet-ca`. Binding and TLS are configured via `app_main_*` (see above).

| Variable | Default | Description |
|----------|---------|-------------|
| `app_puppet_enable` | `true` | Enable the Puppet proxy router group. |
| `app_puppet_serverurl` | *(unset)* | URL of the upstream Puppetserver. If unset, requests are not forwarded. |
| `app_puppet_timeout` | `60` | Upstream request timeout (seconds). |
| `app_puppet_authSecret` | `true` | Apply secret redaction to proxied responses. |
| `app_puppet_trustedCns` | `[]` | JSON list of trusted client CNs allowed for privileged proxy operations. |
| `app_puppet_catalogCache` | `true` | Enable catalog caching. |
| `app_puppet_catalogCacheTTL` | `86400` | TTL (seconds) for cached catalogs. |
| `app_puppet_catalogCacheFacts` | `[]` | JSON list of facts used for granular, fact-based cache invalidation. |

## PuppetDB Proxy (`app_puppetdb_`)

Serves `/pdb`. Binding and TLS are configured via `app_main_*` (see above).

| Variable | Default | Description |
|----------|---------|-------------|
| `app_puppetdb_enable` | `true` | Enable the PuppetDB proxy router group. |
| `app_puppetdb_serverurl` | *(unset)* | URL of the upstream PuppetDB. If unset, requests are not forwarded. |
| `app_puppetdb_timeout` | `60` | Upstream request timeout (seconds). |
| `app_puppetdb_trustedCns` | `[]` | JSON list of trusted client CNs. |
| `app_puppetdb_querySource` | `internal` | Where query results come from: `internal` (pyppetdb's own store) or `upstream` (the configured OpenVoxDB/PuppetDB). Requires `app_puppetdb_serverurl` when set to `upstream`. |
| `app_puppetdb_writeQueueSize` | `500` | Maximum number of commands waiting to be written. Bounds memory: a queued catalog holds its parsed payload (~90 KB for 200 resources), so this is the knob that decides how much RAM a backlog may consume. When the queue is full, `/pdb/cmd/v1` answers `503` with `Retry-After` instead of accumulating work. |
| `app_puppetdb_writeQueueWorkers` | `32` | Number of workers draining the queue, i.e. the cap on concurrent MongoDB write operations. The MongoDB driver pool holds 100 connections by default, so leave headroom for reads. |
| `app_puppetdb_writeQueueDrainTimeout` | `30` | Seconds a graceful shutdown waits for the write queue to drain before the remaining commands are discarded. Bounds how long a restart can block on a backlog; anything still queued when it expires is logged and lost. |
| `app_puppetdb_aggregateCacheTtl` | `60` | Seconds to cache the unfiltered results of `fact-names`, `environments` and `producers`. These group over every node and cannot be narrowed by a filter, so they are recomputed on every request otherwise. Set to `0` to disable; the price of caching is that a newly appearing fact name or environment may take up to this long to show up. |
| `app_puppetdb_maxQueryDepth` | `50` | Maximum nesting depth of a query AST. Rejected with `400` above it. The deepest query in the upstream conformance corpus nests 12 levels, so this leaves ~4x headroom while keeping a deliberately deep query from exhausting the Python stack (which would otherwise surface as a `500`). Set to `0` to disable. |
| `app_puppetdb_maxSubqueryDepth` | `3` | Maximum number of nested subquery levels (`select_*`, `subquery`, a nested `from`). Each level costs one extra MongoDB round trip, so this bounds the work a single request can trigger. The upstream corpus never exceeds 2 and real console traffic never exceeds 1. Set to `0` to disable. |
| `app_puppetdb_queryTimeout` | `600` | Seconds a query may run, matching OpenVoxDB's `query-timeout-default`. Applied both as `maxTimeMS` on every MongoDB operation and as a wall-clock limit around the whole request, so it also bounds the sequential round trips of a nested subquery. A client may override it per request with `?timeout=<seconds>`. Set to `0` for no limit. |
| `app_puppetdb_queryTimeoutMax` | `0` | Upper bound for `?timeout=`, matching OpenVoxDB's `query-timeout-max`. `0` means clients may pick any timeout. |
| `app_puppetdb_resourceQueryInternal` | `true` | **Deprecated.** Superseded by `app_puppetdb_querySource`. When set to `false` it still forces `pdb/query/v4/resources` (and only that endpoint) upstream. |

The current queue depth and the number of accepted, rejected and failed commands are
reported under `/status/v1/services` as `depth`, `accepted`, `dropped` (rejected with a
`503` because the queue was full) and `failed` (accepted with a `200`, then lost because
the background write raised). A `200` from `/pdb/cmd/v1` therefore means *queued*, not
*persisted*: the queue is in memory only, so `failed` and `dropped` are the only signal
that a command did not make it. See
[PuppetDB compatibility](puppetdb.md#what-a-200-means) for the full semantics.

Write commands (`/pdb/cmd/v1`) are always forwarded to `app_puppetdb_serverurl` when
one is configured, regardless of `app_puppetdb_querySource`, and are always stored in
pyppetdb's own database as well. The switch only decides who answers *queries*.

## Certificate Authority (`ca_`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ca_autoSign` | `false` | Automatically sign incoming certificate requests. |
| `ca_autoSignNodeIfExists` | `false` | Auto-sign only if the node already exists in the database. |
| `ca_certificateValidityDays` | `365` | Validity period (days) for issued certificates. |
| `ca_concurrentWorkers` | `5` | Number of concurrent workers for CA signing operations. |
| `ca_enableCrlRefresh` | `true` | Run the background CRL refresh worker. |
| `ca_crlRefreshInterval` | `3600` | Interval (seconds) between CRL refresh runs. |
| `ca_crlValidityDays` | `30` | Validity period (days) of generated CRLs. |
| `ca_verifyCertificateRegistration` | `true` | Require client certificates presented over mTLS to exist (signed) in the database. |
| `ca_verifyCertificateRegistrationCacheTtl` | `300` | TTL (seconds) of the certificate-registration verification cache. |
| `ca_verifyCertificateRegistrationCacheMaxsize` | `1024` | Maximum number of entries in that cache. |

## Jobs (`jobs_`)

| Variable | Default | Description |
|----------|---------|-------------|
| `jobs_maxNodesPerJob` | `1000` | Maximum number of nodes a single job may target. |
| `jobs_expireSeconds` | `3600` | TTL (seconds) for job records and their logs. Because jobs wait as `scheduled` until the agent has a free slot, this also bounds the **maximum time a job may wait in the queue** before it is marked `failed`. Raise it if you expect long queues. |

## MongoDB (`mongodb_`)

| Variable | Default | Description |
|----------|---------|-------------|
| `mongodb_url` | `mongodb://localhost:27017` | MongoDB connection string. A replica set is required. |
| `mongodb_database` | `pyppetdb` | Database name. |
| `mongodb_placementFacts` | `[]` | JSON list of facts used to place documents when using sharded collections. |

## LDAP (`ldap_`)

Optional. When `ldap_url` is set, `ldap_binddn` and `ldap_password` are also required, otherwise
the process exits. Used to synchronize team membership from LDAP groups.

| Variable | Default | Description |
|----------|---------|-------------|
| `ldap_url` | *(unset)* | LDAP server URL. Enables LDAP integration when set. |
| `ldap_basedn` | *(unset)* | Base DN for user/group searches. |
| `ldap_binddn` | *(unset)* | Bind DN used to authenticate against the directory. |
| `ldap_password` | *(unset)* | Password for the bind DN. |
| `ldap_userpattern` | *(unset)* | Search pattern used to resolve users. |

## OAuth (`oauth_<name>_`)

Optional. OAuth providers are configured as a map keyed by a provider name you choose. Each
`<name>` becomes a login provider. Currently the `github` provider `type` is implemented.

| Variable | Description |
|----------|-------------|
| `oauth_<name>_type` | Provider type (e.g. `github`). |
| `oauth_<name>_scope` | Requested OAuth scope. |
| `oauth_<name>_override` | If `true`, treat this provider as the backend of record for the user. |
| `oauth_<name>_client_id` | OAuth client ID. |
| `oauth_<name>_client_secret` | OAuth client secret. |
| `oauth_<name>_url_authorize` | Authorization endpoint URL. |
| `oauth_<name>_url_accesstoken` | Access-token endpoint URL. |
| `oauth_<name>_url_userinfo` | Userinfo endpoint URL (optional). |

Example (GitHub):

```env
oauth_github_type=github
oauth_github_scope=user
oauth_github_override=true
oauth_github_client_id=XXX
oauth_github_client_secret=XXX
oauth_github_url_authorize=https://github.com/login/oauth/authorize
oauth_github_url_accesstoken=https://github.com/login/oauth/access_token
oauth_github_url_userinfo=https://api.github.com/user
```
