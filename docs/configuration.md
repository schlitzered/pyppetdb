# Configuration

pyppetdb is configured via environment variables or a `.env` file. It uses Pydantic for
configuration management, supporting nested settings using the `_` delimiter.

## Deployment Modes

### 1. PuppetDB Replacement & Proxy
In this mode, pyppetdb implements the basic PuppetDB API. It can act as a standalone
service or forward requests to an upstream PuppetDB.

*   **Standalone**: Set `APP_PUPPETDB_ENABLE=true` and leave `APP_PUPPETDB_SERVERURL` empty.
*   **Forwarding**: Set `APP_PUPPETDB_SERVERURL=http://puppetdb.example.com:8080` to
    forward requests that pyppetdb cannot handle natively.

### 2. Puppet CA & Puppetserver Proxy
pyppetdb can replace the Puppet CA and act as a smart reverse proxy for the Puppetserver
API (e.g., for catalog compilation and file serving).

*   **CA Replacement**: Set `CA_ENABLE=true`. pyppetdb will handle certificate signing,
    revocation, and the automatic refresh API.
*   **Puppetserver Proxy**: Set `APP_PUPPET_SERVERURL=https://puppetserver.example.com:8140`.
    pyppetdb will proxy requests to the Puppetserver while providing catalog caching and
    static file serving capabilities.

---

## Configuration Settings

### Global Settings (`APP_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `APP_LOGLEVEL` | `INFO` | Logging level (DEBUG, INFO, WARN, etc.). |
| `APP_SECRETKEY` | `secret` | Secret key used for cryptographic operations. |
| `APP_WSSALT` | `ws-auth` | Salt used for websocket authentication. |

### Main API (`APP_MAIN_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MAIN_ENABLE` | `true` | Enable the main FastAPI management API. |
| `APP_MAIN_HOST` | `0.0.0.0` | Bind address for the main API. |
| `APP_MAIN_PORT` | `8000` | Bind port for the main API. |
| `APP_MAIN_INTERAPIIDLETIMEOUT` | `300` | Timeout for inter-API communication. |

### Puppet Proxy (`APP_PUPPET_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PUPPET_ENABLE` | `true` | Enable the Puppetserver proxy. |
| `APP_PUPPET_HOST` | `0.0.0.0` | Bind address for the Puppet proxy. |
| `APP_PUPPET_PORT` | `8001` | Bind port for the Puppet proxy. |
| `APP_PUPPET_SERVERURL` | `None` | URL of the upstream Puppetserver. |
| `APP_PUPPET_CATALOGCACHE` | `true` | Enable catalog caching. |
| `APP_PUPPET_CATALOGCACHETTL` | `86400` | TTL for cached catalogs (seconds). |
| `APP_PUPPET_CATALOGCACHEFACTS` | `[]` | List of facts used for granular cache invalidation. |
| `APP_PUPPET_AUTHSECRET` | `true` | Enable secret redaction in proxy responses. |

### PuppetDB Proxy (`APP_PUPPETDB_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PUPPETDB_ENABLE` | `true` | Enable the PuppetDB proxy. |
| `APP_PUPPETDB_HOST` | `127.0.0.1` | Bind address for the PuppetDB proxy. |
| `APP_PUPPETDB_PORT` | `8002` | Bind port for the PuppetDB proxy. |
| `APP_PUPPETDB_SERVERURL` | `None` | URL of the upstream PuppetDB. |

### Certificate Authority (`CA_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `CA_AUTOSIGN` | `false` | Enable automatic certificate signing. |
| `CA_AUTOSIGNNODEIFEXISTS` | `false` | Auto-sign if the node already exists in the database. |
| `CA_CERTIFICATEVALIDITYDAYS` | `365` | Validity period for issued certificates. |
| `CA_CONCURRENTWORKERS` | `5` | Number of workers for CA operations. |

### MongoDB (`MONGODB_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string. |
| `MONGODB_DATABASE` | `pyppetdb` | Database name. |
| `MONGODB_PLACEMENTFACTS` | `[]` | Facts used for node placement logic. |

### Hiera (`HIERA_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `HIERA_ENABLE` | `true` | Enable the PyHiera backend. |

### Jobs (`JOBS_`)
| Variable | Default | Description |
|----------|---------|-------------|
| `JOBS_MAXNODESPERJOB` | `1000` | Limit of nodes targeted per job. |
| `JOBS_EXPIRESECONDS` | `3600` | TTL for job data and logs. |

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
