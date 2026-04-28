# Setup and Configuration

This guide covers the installation of **pyppetdb** and how to configure it for your environment.

## Installation

### Prerequisites

pyppetdb is strictly tested on **Python 3.12**. While it may run on other versions, all
dependencies in `requirements.txt` are verified against the 3.12 runtime. It is highly
recommended to run pyppetdb within a dedicated virtual environment.

### System Dependencies

pyppetdb utilizes the `bonsai` library for optional LDAP integration (used to synchronize
teams with LDAP group members). To install this dependency, your system must have LDAP
development headers and a C compiler installed.

**On Debian/Ubuntu:**
```bash
sudo apt-get install build-essential python3.12-dev libldap2-dev libsasl2-dev
```

**On RHEL/CentOS:**
```bash
sudo yum install gcc python3.12-devel openldap-devel cyrus-sasl-devel
```

### Recommended Setup

1.  **Create a Virtual Environment:**
    ```bash
    python3.12 -m venv /opt/pyppetdb
    source /opt/pyppetdb/bin/activate
    ```

2.  **Install pyppetdb:**
    You can install pyppetdb directly via pip:
    ```bash
    pip install pyppetdb
    ```

3.  **Install from Source (Development):**
    If you are installing from the repository:
    ```bash
    git clone https://github.com/schlitzered/pyppetdb.git
    cd pyppetdb
    pip install -r requirements.txt
    ```

---

## Configuration
### Pyppetdb
pyppetdb is configured via environment variables or a `.env` file. It uses Pydantic for
configuration management, supporting nested settings using the `_` delimiter.

**Note:** Configuration keys are case-sensitive. Nested settings use the `_` delimiter to
map to the internal model structure.


Below is an example of a production-ready configuration using a .env file.
The env file needs to be placed in the working directory of pyppetdb, example /opt/pyppetdb/.env

```env
# security related settings
app_secretkey=SomethingSuperSecretHere
app_wssalt=AnotherSuperSecretSecret

# Main API Settings
app_main_facts_index=[ "role", "stage", "location", "provider" ]
app_main_host=0.0.0.0
app_main_ssl_ca=/etc/puppetlabs/puppet/ssl/certs/ca.pem
app_main_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.example.com.pem
app_main_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.example.com.pem

# Puppet Proxy Settings
app_puppet_port=8140 # we are taking over the puppetserver port
app_puppet_serverurl=http://127.0.0.1:8144 # the puppetserver instance on the same node
app_puppet_ssl_ca=/etc/puppetlabs/puppet/ssl/certs/ca.pem
app_puppet_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.example.com.pem
app_puppet_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.example.com.pem
app_puppet_catalogCacheFacts=[ "role", "stage", "location", "provider" ]
app_puppet_catalogCache=True
app_puppet_trustedCns=[ "puppetsrv-1.example.com" ] # usually it is enough if this is to the fqdn of the current node

# PuppetDB Proxy Settings
app_puppetdb_host=0.0.0.0
app_puppetdb_serverurl=http://127.0.0.1:8080 # if omitted, will not forward requests to real puppetdb
app_puppetdb_ssl_ca=/etc/puppetlabs/puppet/ssl/certs/ca.pem
app_puppetdb_ssl_cert=/etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.example.com.pem
app_puppetdb_ssl_key=/etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.example.com.pem
app_puppetdb_trustedCns=[ "puppetsrv-1.example.com" ] # usually it is enough if this is to the fqdn of the current node

# MongoDB Settings
# this is used if you like to shard the shard-able collections
mongodb_placementFacts=[ "role", "stage", "location", "provider" ]
```

### puppetserver
puppet server needs to get reconfigured. ssl needs to be disabled,
and it needs to read the CN from a header instead of cert itself,
this is needed because pyppetdb is executing the mtls validation with the agent.


**`/etc/puppetlabs/puppetserver/conf.d/webserver.conf`**
```hocon
webserver: {
    access-log-config: /etc/puppetlabs/puppetserver/request-logging.xml
    client-auth: want
    host: 127.0.0.1 # for security reason, only listen on localhost
    port: 8144 # we adjust the port, since pyppetdb will take over
    #ssl-host: 0.0.0.0
    #ssl-port: 8140
    #ssl-cert: /etc/puppetlabs/puppet/ssl/certs/puppetsrv-1.example.com.pem
    #ssl-key: /etc/puppetlabs/puppet/ssl/private_keys/puppetsrv-1.example.com.pem
    #ssl-ca-cert: /etc/puppetlabs/puppet/ssl/certs/ca.pem

}
```
we need to set "allow-header-cert-info: true", so puppetserver picks up cert info from headers.
We only show the complete file here, for completeness,
but you actually only need to add the single line at the right place

**`/etc/puppetlabs/puppetserver/conf.d/auth.conf`**
```hocon
authorization: {
    version: 1
    allow-header-cert-info: true
    rules: [
        {
            # Allow nodes to retrieve their own catalog
            match-request: {
                path: "^/puppet/v3/catalog/([^/]+)$"
                type: regex
                method: [get, post]
            }
            allow: "$1"
            sort-order: 500
            name: "puppetlabs v3 catalog from agents"
        },
        {
            # Allow services to retrieve catalogs on behalf of others
            match-request: {
                path: "^/puppet/v4/catalog/?$"
                type: regex
                method: post
            }
            deny: "*"
            sort-order: 500
            name: "puppetlabs v4 catalog for services"
        },
        {
            # Allow nodes to retrieve the certificate they requested earlier
            match-request: {
                path: "/puppet-ca/v1/certificate/"
                type: path
                method: get
            }
            allow-unauthenticated: true
            sort-order: 500
            name: "puppetlabs certificate"
        },
        {
            # Allow all nodes to access the certificate revocation list
            match-request: {
                path: "/puppet-ca/v1/certificate_revocation_list/ca"
                type: path
                method: get
            }
            allow-unauthenticated: true
            sort-order: 500
            name: "puppetlabs crl"
        },
        {
            # Allow nodes to request a new certificate
            match-request: {
                path: "/puppet-ca/v1/certificate_request"
                type: path
                method: [get, put]
            }
            allow-unauthenticated: true
            sort-order: 500
            name: "puppetlabs csr"
        },
        {
            # Allow nodes to renew their certificate
            match-request: {
                path: "/puppet-ca/v1/certificate_renewal"
                type: path
                method: post
            }
            # this endpoint should never be unauthenticated, as it requires the cert to be provided.
            allow: "*"
            sort-order: 500
            name: "puppetlabs certificate renewal"
        },
        {
            # Allow the CA CLI to access the certificate_status endpoint
            match-request: {
                path: "/puppet-ca/v1/certificate_status"
                type: path
                method: [get, put, delete]
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs cert status"
        },
        {
            match-request: {
                path: "^/puppet-ca/v1/certificate_revocation_list$"
                type: regex
                method: put
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs CRL update"
        },
        {
            # Allow the CA CLI to access the certificate_statuses endpoint
            match-request: {
                path: "/puppet-ca/v1/certificate_statuses"
                type: path
                method: get
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs cert statuses"
        },
        {
            # Allow authenticated access to the CA expirations endpoint
            match-request: {
                path: "/puppet-ca/v1/expirations"
                type: path
                method: get
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs CA cert and CRL expirations"
        },
        {
            # Allow the CA CLI to access the certificate clean endpoint
            match-request: {
                path: "/puppet-ca/v1/clean"
                type: path
                method: put
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs cert clean"
        },
        {
            # Allow the CA CLI to access the certificate sign endpoint
            match-request: {
                path: "/puppet-ca/v1/sign"
                type: path
                method: post
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs cert sign"
        },
        {
            # Allow the CA CLI to access the certificate sign all endpoint
            match-request: {
                path: "/puppet-ca/v1/sign/all"
                type: path
                method: post
            }
            allow: {
               extensions: {
                   pp_cli_auth: "true"
               }
            }
            sort-order: 500
            name: "puppetlabs cert sign all"
        },
        {
            # Allow unauthenticated access to the status service endpoint
            match-request: {
                path: "/status/v1/services"
                type: path
                method: get
            }
            allow-unauthenticated: true
            sort-order: 500
            name: "puppetlabs status service - full"
        },
        {
            match-request: {
                path: "/status/v1/simple"
                type: path
                method: get
            }
            allow-unauthenticated: true
            sort-order: 500
            name: "puppetlabs status service - simple"
        },
        {
            match-request: {
                path: "/puppet/v3/environments"
                type: path
                method: get
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs environments"
        },
        {
            # Allow nodes to access all file_bucket_files.  Note that access for
            # the 'delete' method is forbidden by Puppet regardless of the
            # configuration of this rule.
            match-request: {
                path: "/puppet/v3/file_bucket_file"
                type: path
                method: [get, head, post, put]
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs file bucket file"
        },
        {
            # Allow nodes to access all file_content.  Note that access for the
            # 'delete' method is forbidden by Puppet regardless of the
            # configuration of this rule.
            match-request: {
                path: "/puppet/v3/file_content"
                type: path
                method: [get, post]
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs file content"
        },
        {
            # Allow nodes to access all file_metadata.  Note that access for the
            # 'delete' method is forbidden by Puppet regardless of the
            # configuration of this rule.
            match-request: {
                path: "/puppet/v3/file_metadata"
                type: path
                method: [get, post]
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs file metadata"
        },
        {
            # Allow nodes to retrieve only their own node definition
            match-request: {
                path: "^/puppet/v3/node/([^/]+)$"
                type: regex
                method: get
            }
            allow: "$1"
            sort-order: 500
            name: "puppetlabs node"
        },
        {
            # Allow nodes to store only their own reports
            match-request: {
                path: "^/puppet/v3/report/([^/]+)$"
                type: regex
                method: put
            }
            allow: "$1"
            sort-order: 500
            name: "puppetlabs report"
        },
        {
            # Allow nodes to update their own facts
            match-request: {
                path: "^/puppet/v3/facts/([^/]+)$"
                type: regex
                method: put
            }
            allow: "$1"
            sort-order: 500
            name: "puppetlabs facts"
        },
        {
            match-request: {
                path: "/puppet/v3/static_file_content"
                type: path
                method: get
            }
            allow: "*"
            sort-order: 500
            name: "puppetlabs static file content"
        },
        {
            match-request: {
                path: "/puppet/v3/tasks"
                type: path
            }
            allow: "*"
            sort-order: 500
            name: "puppet tasks information"
        },
        {
            # Deny everything else. This ACL is not strictly
            # necessary, but illustrates the default policy
            match-request: {
                path: "/"
                type: path
            }
            deny: "*"
            sort-order: 999
            name: "puppetlabs deny all"
        }
    ]
}
```

**`/etc/puppetlabs/puppet/puppetdb.conf`**
```ini
[main]
server_urls = https://puppetsrv-1.example.com:8002
```

### PuppetDB
No config changes needed on PuppetDB


## MongoDB Setup

**pyppetdb** requires a MongoDB **Replica Set** to function correctly, even if you are only running a single-node instance.
This is because the application makes heavy use of **MongoDB Change Streams**
to react to data modifications in real-time, which avoids the performance overhead of constant database polling.

### Single-Node Development Setup (No Password)

For development or small-scale testing, you can initialize a single-node replica set with the following steps:

1.  **Install MongoDB**: Follow the [official MongoDB installation guide](https://www.mongodb.com/docs/manual/installation/) for your operating system.
2.  **Configure Replication**: Edit your `mongod.conf` (usually in `/etc/mongod.conf`) to enable replication:
    ```yaml
    replication:
      replSetName: "rs0"
    ```
3.  **Restart and Initialize**: Restart the MongoDB service and initialize the replica set via the `mongosh` shell:
    ```bash
    sudo systemctl restart mongod
    mongosh --eval "rs.initiate()"
    ```

### Production Recommendations

*   **High Availability**: For production environments, it is strongly recommended to deploy at least a **3-node replica set** to ensure fault tolerance and data consistency.
*   **Security**: Always enable authentication and configure robust Access Control Lists (ACLs).
*   **Sharding**: pyppetdb supports sharded MongoDB clusters for massive scale. Detailed instructions for configuring node placement and sharding will be covered on a separate page.

---

## Web Server Configuration


### Nginx

Nginx is used to serve the `pyppetdb-web` frontend and act as a reverse proxy for the `pyppetdb` API.

#### 1. Install Nginx
On Debian/Ubuntu:
```bash
sudo apt-get install nginx
```

#### 2. Install pyppetdb-web
```bash
sudo mkdir -p /opt/pyppetdb_web
cd /opt/pyppetdb_web
sudo wget https://github.com/schlitzered/pyppetdb-web/releases/download/v0.0.4/pyppetdb-web-0.0.4.tar.gz
sudo tar xf pyppetdb-web-0.0.4.tar.gz
sudo rm pyppetdb-web-0.0.4.tar.gz
```

#### 3. Configure Nginx
Create a new configuration file at **`/etc/nginx/conf.d/pyppetdb.conf`**:

```nginx
server {
    listen 80;
    server_name _; # Change this to your domain if needed

    root /opt/pyppetdb_web/;
    index index.html;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # Single Page Application routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API Proxy and WebSockets
    location ~ ^/(api|docs|oauth|openapi\.json|versions) {
        proxy_pass https://127.0.0.1:8000;
        
        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Increase timeouts for long-running log streams
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Static assets caching
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Content-Type-Options "nosniff";
}
```

#### 4. Enable and Start Nginx
```bash
sudo systemctl enable nginx
sudo systemctl start nginx
```

### Apache

Apache can be used as an alternative to Nginx. Ensure the following modules are enabled: `proxy`, `proxy_http`, `proxy_wstunnel`, `rewrite`, `headers`, `deflate`, and `ssl`.

#### 1. Enable Required Modules
```bash
sudo a2enmod proxy proxy_http proxy_wstunnel rewrite headers deflate ssl
```

#### 2. Configure Apache
Create a new virtual host configuration, for example at **`/etc/apache2/sites-available/pyppetdb.conf`**:

```apache
<VirtualHost *:80>
    ServerName _; # Change this to your domain if needed
    DocumentRoot /opt/pyppetdb_web

    <Directory /opt/pyppetdb_web>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted

        # Single Page Application routing
        RewriteEngine On
        RewriteBase /
        RewriteRule ^index\.html$ - [L]
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteCond %{REQUEST_FILENAME} !-d
        RewriteRule . /index.html [L]
    </Directory>

    # API Proxy and WebSockets settings for Backend
    SSLProxyEngine on
    SSLProxyVerify none
    SSLProxyCheckPeerCN off
    SSLProxyCheckPeerName off
    SSLProxyCheckPeerExpire off

    ProxyRequests Off
    ProxyPreserveHost On

    # WebSocket support (must come before standard proxy)
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/(api|docs|oauth|openapi\.json|versions)(.*) wss://127.0.0.1:8000/$1$2 [P,L]

    # Standard proxy for API paths
    ProxyPassMatch ^/(api|docs|oauth|openapi\.json|versions) https://127.0.0.1:8000
    ProxyPassReverse / https://127.0.0.1:8000

    # Increase timeouts for long-running log streams
    ProxyTimeout 3600

    # Compression
    AddOutputFilterByType DEFLATE text/plain text/html text/xml text/css application/xml application/xhtml+xml application/rss+xml application/javascript application/x-javascript application/json

    # Static assets caching
    <LocationMatch "^/assets/">
        Header set Cache-Control "max-age=31536000, public, no-transform"
    </LocationMatch>

    # Security headers
    Header set X-Frame-Options "SAMEORIGIN"
    Header set X-XSS-Protection "1; mode=block"
    Header set X-Content-Type-Options "nosniff"
</VirtualHost>
```

#### 3. Enable the Site and Restart Apache
```bash
sudo a2ensite pyppetdb.conf
sudo systemctl restart apache2
```

---

## Initialization

Before starting the service, you must perform several one-time initialization steps.
Ensure you have your virtual environment activated and are in the pyppetdb directory.

```bash
source /opt/pyppetdb/bin/activate
cd /opt/pyppetdb
```

The `pyppetdb` command provides several sub-commands for initialization:

```bash
pyppetdb --help
```

**Output:**
```text
usage: pyppetdb [-h] {create-admin,init-ca,import-puppet-ca} ...

positional arguments:
  {create-admin,init-ca,import-puppet-ca}
    create-admin        create an admin user
    init-ca             initialize the default puppet ca and generate a server cert
    import-puppet-ca    Import an existing Puppet CA into pyppetdb

options:
  -h, --help            show this help message and exit
```

### 1. Create Administrative User

Use the `create-admin` command to set up your first user.

```bash
# Check available options
pyppetdb create-admin --help
```

**Output:**
```text
usage: pyppetdb create-admin [-h] [--user-id USER_ID] [--email EMAIL] [--name NAME] [--password PASSWORD]

options:
  -h, --help           show this help message and exit
  --user-id USER_ID
  --email EMAIL
  --name NAME
  --password PASSWORD
```

**Example Call:**
```bash
pyppetdb create-admin --user-id admin --email admin@example.com --name "System Admin" --password "ChangeMe123!"
```

### 2. Configure Certificate Authority

Depending on your environment, you can either import an existing Puppet CA or initialize a completely fresh one.

#### Option A: Import Existing Puppet CA
If you are migrating from a standard Puppetserver, you can import the existing CA directory.

```bash
pyppetdb import-puppet-ca --help
```

**Output:**
```text
usage: pyppetdb import-puppet-ca [-h] --ca-dir CA_DIR

options:
  -h, --help       show this help message and exit
  --ca-dir CA_DIR  Path to the Puppet CA directory (e.g., /etc/puppetlabs/puppetserver/ca)
```

**Example Call:**
```bash
pyppetdb import-puppet-ca --ca-dir /etc/puppetlabs/puppetserver/ca
```

#### Option B: Initialize Fresh CA
If you are starting from scratch, use `init-ca` to generate the root certificates and the initial server certificate.

```bash
pyppetdb init-ca --help
```

**Output:**
```text
usage: pyppetdb init-ca [-h] [--cn CN] [--alt-names ALT_NAMES] [--ca-path CA_PATH] [--cert-path CERT_PATH] [--key-path KEY_PATH]

options:
  -h, --help            show this help message and exit
  --cn CN               The common name for the server certificate
  --alt-names ALT_NAMES
                        Optional comma-separated list of SANs
  --ca-path CA_PATH     Path to save the CA certificate (default: /etc/puppetlabs/puppet/ssl/certs/ca.pem)
  --cert-path CERT_PATH
                        Path to save the server certificate
  --key-path KEY_PATH   Path to save the server private key
```

---

## Starting pyppetdb

Once initialized, you can start the application by running the `pyppetdb` command. Note that the process runs in the foreground by default.

### Systemd Unit File

For production deployments, it is recommended to run pyppetdb as a systemd service. Create the following file at **`/etc/systemd/system/pyppetdb.service`**:

```ini
[Unit]
Description=pyppetdb service
After=network.target mongodb.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/pyppetdb
ExecStart=/opt/pyppetdb/bin/pyppetdb
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and Start
```bash
sudo systemctl daemon-reload
sudo systemctl enable pyppetdb
sudo systemctl start pyppetdb
```
