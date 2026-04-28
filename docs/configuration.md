# Configuration

pyppetdb is configured via environment variables or a `.env` file. It uses Pydantic for
configuration management, supporting nested settings using the `_` delimiter.

**Note:** Configuration keys are case-sensitive. Nested settings use the `_` delimiter to
map to the internal model structure.

## Deployment Modes

### 1. PuppetDB Replacement & Proxy
In this mode, pyppetdb implements the basic PuppetDB API. It can act as a standalone
service or forward requests to an upstream PuppetDB.

*   **Standalone**: Set `app_puppetdb_enable=true` and leave `app_puppetdb_serverurl` empty.
*   **Forwarding**: Set `app_puppetdb_serverurl=http://puppetdb.example.com:8080` to
    forward requests that pyppetdb cannot handle natively.

### 2. Puppet CA & Puppetserver Proxy
pyppetdb can replace the Puppet CA and act as a smart reverse proxy for the Puppetserver
API (e.g., for catalog compilation and file serving).

*   **CA Replacement**: Set `ca_enable=true`. pyppetdb will handle certificate signing,
    revocation, and the automatic refresh API.
*   **Puppetserver Proxy**: Set `app_puppet_serverurl=https://puppetserver.example.com:8140`.
    pyppetdb will proxy requests to the Puppetserver while providing catalog caching and
    static file serving capabilities.

---

## Example Configuration

Below is an example of a production-ready configuration using environment variables. This setup includes SSL configuration and uses a specific set of facts for indexing and caching.

```bash
# security related settings
app_secretkey=SomethingSuperSecretHere
app_wssalt=AnotherSuperSecretSecret

# Main API Settings
app_main_facts_index=[ "role", "stage", "location", "provider" ]
app_main_host=0.0.0.0
app_main_port=8140
app_main_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem
app_main_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem

# Puppet Proxy Settings
app_puppet_serverurl=http://puppetsrv-1.prod.home.dc.linux.schlitzered.de:8140
app_puppet_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem
app_puppet_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem
app_puppet_ssl_ca=/etc/puppetlabs/puppet/ssl/certs/ca.pem
app_puppet_catalogCacheFacts=[ "role", "stage", "location", "provider" ]
app_puppet_catalogCache=False
app_puppet_trustedCns=[ "puppetsrv-1.prod.home.dc.linux.schlitzered.de" ]

# PuppetDB Proxy Settings
app_puppetdb_host=0.0.0.0
app_puppetdb_serverurl=http://127.0.0.1:8080
app_puppetdb_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem
app_puppetdb_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.prod.home.dc.linux.schlitzered.de.pem
app_puppetdb_ssl_ca=/etc/puppetlabs/puppet/ssl/certs/ca.pem
app_puppetdb_trustedCns=[ "puppetsrv-1.prod.home.dc.linux.schlitzered.de" ]

# MongoDB Settings
mongodb_placementFacts=[ "role", "stage", "location", "provider" ]
```

---

## Configuration Settings

### Global Settings (`app_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `app_loglevel` | `INFO` | Logging level (DEBUG, INFO, WARN, etc.). |
| `app_secretkey` | `secret` | Secret key used for cryptographic operations. |
| `app_wssalt` | `ws-auth` | Salt used for websocket authentication. |

### Main API (`app_main_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `app_main_enable` | `true` | Enable the main FastAPI management API. |
| `app_main_host` | `0.0.0.0` | Bind address for the main API. |
| `app_main_port` | `8000` | Bind port for the main API. |
| `app_main_ssl_cert` | `None` | Path to the SSL certificate. |
| `app_main_ssl_key` | `None` | Path to the SSL private key. |
| `app_main_facts_index` | `None` | Facts used for indexing in the database. |
| `app_main_interApiIdleTimeout` | `300` | Timeout for inter-API communication. |

### Puppet Proxy (`app_puppet_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `app_puppet_enable` | `true` | Enable the Puppetserver proxy. |
| `app_puppet_host` | `0.0.0.0` | Bind address for the Puppet proxy. |
| `app_puppet_port` | `8001` | Bind port for the Puppet proxy. |
| `app_puppet_serverurl` | `None` | URL of the upstream Puppetserver. |
| `app_puppet_ssl_cert` | `None` | Path to the SSL certificate for proxying. |
| `app_puppet_ssl_key` | `None` | Path to the SSL private key for proxying. |
| `app_puppet_ssl_ca` | `None` | Path to the CA certificate for validation. |
| `app_puppet_trustedCns` | `[]` | List of trusted Common Names for SSL validation. |
| `app_puppet_catalogCache` | `true` | Enable catalog caching. |
| `app_puppet_catalogCacheTTL` | `86400` | TTL for cached catalogs (seconds). |
| `app_puppet_catalogCacheFacts` | `[]` | List of facts used for granular cache invalidation. |
| `app_puppet_authSecret` | `true` | Enable secret redaction in proxy responses. |

### PuppetDB Proxy (`app_puppetdb_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `app_puppetdb_enable` | `true` | Enable the PuppetDB proxy. |
| `app_puppetdb_host` | `127.0.0.1` | Bind address for the PuppetDB proxy. |
| `app_puppetdb_port` | `8002` | Bind port for the PuppetDB proxy. |
| `app_puppetdb_serverurl` | `None` | URL of the upstream PuppetDB. |
| `app_puppetdb_ssl_cert` | `None` | Path to the SSL certificate for proxying. |
| `app_puppetdb_ssl_key` | `None` | Path to the SSL private key for proxying. |
| `app_puppetdb_ssl_ca` | `None` | Path to the CA certificate for validation. |
| `app_puppetdb_trustedCns` | `[]` | List of trusted Common Names for SSL validation. |

### Certificate Authority (`ca_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ca_autoSign` | `false` | Enable automatic certificate signing. |
| `ca_autoSignNodeIfExists` | `false` | Auto-sign if the node already exists in the database. |
| `ca_certificateValidityDays` | `365` | Validity period for issued certificates. |
| `ca_concurrentWorkers` | `5` | Number of workers for CA operations. |
| `ca_enableCrlRefresh` | `true` | Enable automatic CRL refresh. |

### MongoDB (`mongodb_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `mongodb_url` | `mongodb://localhost:27017` | MongoDB connection string. |
| `mongodb_database` | `pyppetdb` | Database name. |
| `mongodb_placementFacts` | `[]` | Facts used for node placement logic. |

### Hiera (`hiera_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `hiera_enable` | `true` | Enable the PyHiera backend. |

### Jobs (`jobs_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `jobs_maxNodesPerJob` | `1000` | Limit of nodes targeted per job. |
| `jobs_expireSeconds` | `3600` | TTL for job data and logs. |

---

## Web Server Configuration

### Nginx (Example)
```nginx
# TBD: Example configuration for Nginx as a reverse proxy
```

### Apache (Example)
```apache
# TBD: Example configuration for Apache as a reverse proxy
```
