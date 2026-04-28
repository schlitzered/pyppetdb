# Configuration Reference

This page provides a detailed reference of all configuration variables available in **pyppetdb**.

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
