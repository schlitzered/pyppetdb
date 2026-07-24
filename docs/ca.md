# Certificate Authority

pyppetdb implements the **Puppet CA API** and stores all CA state (authorities, issued
certificates, secrets, CRLs) in MongoDB. Because the CA is database-backed rather than
filesystem-backed, **every** pyppetdb instance can act as a CA — there is no single-node CA to fail
over and no shared filesystem or `keepalived` setup required.

## Concepts

* **CA Authority** — a signing CA (certificate + private key). The default authority used for
  Puppet is `puppet-ca`. Authorities can be chained (an authority may have a `parent_id`).
* **CA Space** — a namespace that binds incoming certificate requests to a specific authority and a
  **validation configuration**. The `puppet-ca` space is used for Puppet agent enrollment. Spaces
  keep a `ca_id_history` so certificates signed by a previously-used authority remain valid.
* **Certificate** — an issued/known certificate, tracked by serial number, CN and status.
* **CA Secret** — an encrypted secret stored in pyppetdb (see [secret redaction](index.md#advanced-secrets-redaction)).

## Signing behaviour

Signing is controlled by the `ca_*` settings (see the
[Configuration Reference](configuration_reference.md#certificate-authority-ca_)):

* `ca_autoSign` — automatically sign incoming requests.
* `ca_autoSignNodeIfExists` — auto-sign only when the node already exists in the database.
* `ca_certificateValidityDays` — validity of issued certificates.
* CRLs are refreshed by a background worker when `ca_enableCrlRefresh` is set
  (`ca_crlRefreshInterval`, `ca_crlValidityDays`).

### mTLS certificate verification

When TLS is enabled with a client CA (`app_main_ssl_ca`), client certificates presented by Puppet
agents are validated against pyppetdb's own records. With `ca_verifyCertificateRegistration`
enabled (default), a presented certificate must exist in the database as a signed certificate whose
serial and CN match — otherwise access is denied. Lookups are cached
(`ca_verifyCertificateRegistrationCacheTtl`, `ca_verifyCertificateRegistrationCacheMaxsize`).

## Space validation configuration

Each CA space carries a `validation_config` that governs which certificate requests may be signed:

* `enforce_rfc1123` — require RFC 1123-compliant names.
* `allowed_extensions` — allow-list of certificate extensions.
* `key_usages` / `extended_key_usages` — enforced key usage constraints.
* `san_validation` — bounds and checks on Subject Alternative Names: `max_san_count`, regex
  allow-lists, external HTTP checks, and external script checks.
* `san_injection` — inject additional SANs based on a matching pattern.

## Puppet CA endpoints (agent-facing)

Served by a Puppet proxy instance under `/puppet-ca/v1` (mTLS):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/puppet-ca/v1/certificate/{nodename}` | Retrieve a signed certificate. |
| `GET` | `/puppet-ca/v1/certificate_request/{nodename}` | Retrieve a pending CSR. |
| `PUT` | `/puppet-ca/v1/certificate_request/{nodename}` | Submit a CSR. |
| `GET` | `/puppet-ca/v1/certificate_status/{nodename}` | Get certificate status. |
| `PUT` | `/puppet-ca/v1/certificate_status/{nodename}` | Sign a pending request. |
| `DELETE` | `/puppet-ca/v1/certificate_status/{nodename}` | Revoke / clean a certificate. |
| `GET` | `/puppet-ca/v1/certificate_revocation_list/ca` | Retrieve the CRL. |
| `POST` | `/puppet-ca/v1/certificate_renewal` | Renew the caller's certificate (the undocumented Puppet auto-refresh endpoint). |

## CA management API

Served by the Management API under `/api/v1` for operators and the web UI:

### Authorities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ca/authorities` | List authorities. |
| `POST` | `/api/v1/ca/authorities/{ca_id}` | Create an authority. |
| `GET` | `/api/v1/ca/authorities/{ca_id}` | Get an authority. |
| `PUT` | `/api/v1/ca/authorities/{ca_id}` | Update an authority. |
| `DELETE` | `/api/v1/ca/authorities/{ca_id}` | Delete an authority. |
| `GET` | `/api/v1/ca/authorities/{ca_id}/certs` | List certificates for an authority. |
| `GET` | `/api/v1/ca/authorities/{ca_id}/certs/{cert_id}` | Get a certificate. |
| `PUT` | `/api/v1/ca/authorities/{ca_id}/certs/{cert_id}` | Update a certificate (e.g. sign/revoke). |

### Spaces

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ca/spaces` | List spaces. |
| `POST` | `/api/v1/ca/spaces/{space_id}` | Create a space. |
| `GET` | `/api/v1/ca/spaces/{space_id}` | Get a space. |
| `PUT` | `/api/v1/ca/spaces/{space_id}` | Update a space (incl. `validation_config`). |
| `DELETE` | `/api/v1/ca/spaces/{space_id}` | Delete a space. |
| `GET` | `/api/v1/ca/spaces/{space_id}/certs` | List certificates in a space. |
| `GET` | `/api/v1/ca/spaces/{space_id}/certs/{cert_id}` | Get a certificate. |
| `PUT` | `/api/v1/ca/spaces/{space_id}/certs/{cert_id}` | Update a certificate. |

### Secrets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ca/secrets` | List secrets. |
| `POST` | `/api/v1/ca/secrets/{secret_id}` | Create a secret. |
| `GET` | `/api/v1/ca/secrets/{secret_id}` | Get a secret. |
| `PUT` | `/api/v1/ca/secrets/{secret_id}` | Update a secret. |
| `DELETE` | `/api/v1/ca/secrets/{secret_id}` | Delete a secret. |

## Initialising the CA

Use the `pyppetdb init-ca` command to create a fresh CA and server certificate, or
`pyppetdb import-puppet-ca` to migrate an existing Puppetserver CA. See
[Setup → Configure Certificate Authority](setup.md#2-configure-certificate-authority).
