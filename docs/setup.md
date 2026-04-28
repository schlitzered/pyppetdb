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

For a complete list of all configuration variables, see the [Configuration Reference](configuration_reference.md).

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
