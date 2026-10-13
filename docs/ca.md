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
* `san_injection` — inject additional SANs when a pattern matches the whole CN.

SANs requested in a CSR are only kept when `san_validation` is configured on the authority or
the space. Renewals follow the same rule: without `san_validation`, a renewed certificate
carries the CN and the injected SANs, but not the SANs of the old certificate.

External script checks run with a minimal environment: `PATH`, `CN` and `SAN1`, `SAN2`, ….
A non-zero exit code rejects the request. The requester only sees a generic error; the exit
code and the script output are written to the pyppetdb log. HTTP checks behave the same way
for status codes and connection errors.

A revoked authority cannot sign certificates or intermediate authorities any more.
Revocations reach the CRLs with the next refresh of the CRL worker.

An authority can only be revoked once no space uses it and all of its sub-authorities are
revoked, so a hierarchy is revoked bottom-up. To retire an authority, point its spaces to a
new one first. Spaces cannot be created on or moved to a revoked authority.

Certificates issued by a revoked authority, or by any authority below a revoked one, are no
longer accepted for mTLS on `/puppet` and `/pdb` (with `ca_verifyCertificateRegistration`
enabled), and `certificate_status` reports them as `revoked` to Puppet. Their documents are
not rewritten.

Every certificate remembers the SANs its requester asked for (`requested_sans`, taken from
the CSR, or for imported certificates from the certificate without its CN). Renewals run the
same name checks as new requests (RFC 1123, SAN count and regex, HTTP and script checks) on
these SANs against the current configuration, and the renewed certificate carries the CN,
the requested SANs (when `san_validation` is configured) and the SANs the current
`san_injection` rules add — SANs injected by rules that no longer match are dropped.

Pending certificate requests expire `ca_certificateRequestTtlDays` after their last
submission and are removed by MongoDB; signing a request removes the expiry.

## Puppet CA endpoints (agent-facing)

Served under `/puppet-ca/v1` (Puppet proxy router group, mTLS):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/puppet-ca/v1/certificate/{nodename}` | Retrieve a signed certificate. |
| `GET` | `/puppet-ca/v1/certificate_request/{nodename}` | Retrieve a pending CSR. |
| `PUT` | `/puppet-ca/v1/certificate_request/{nodename}` | Submit a CSR. |
| `GET` | `/puppet-ca/v1/certificate_status/{nodename}` | Get certificate status. |
| `PUT` | `/puppet-ca/v1/certificate_status/{nodename}` | Sign a pending request. |
| `DELETE` | `/puppet-ca/v1/certificate_status/{nodename}` | Clean a node: revoke its signed certificate and drop its requests. |
| `GET` | `/puppet-ca/v1/certificate_revocation_list/ca` | Retrieve the CRL. |
| `POST` | `/puppet-ca/v1/certificate_renewal` | Renew the caller's certificate (the undocumented Puppet auto-refresh endpoint). |

Signed certificates are never deleted, only revoked; revoked ones stay in the database until
they expire. The Puppet CA endpoints only see the active certificate of a node — its pending
request or its signed certificate, of which there is at most one — so a revoked certificate
looks deleted to them: `certificate_status` answers 404.

A certificate request is not a certificate: revoking a pending request — through the Puppet CA
endpoints or the management API — deletes it instead of keeping a revoked document, which
would carry no expiry date and stay forever. The management API still answers with the request
as it was, marked `revoked`.

`puppetserver ca clean` sends a `PUT` with `desired_state: revoked` followed by the `DELETE`
above. The `DELETE` revokes the signed certificate if it is still active and deletes the node's
requests, after which the node can submit a new request. Because the preceding `PUT` may
already have revoked the certificate or deleted the request, the `DELETE` always answers 204,
also for a node the CA does not know.

## CA management API

Served by the Management API under `/api/v1` for operators and the web UI:

### Authorities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ca/authorities` | List authorities (`secret_ref` filters by a referenced secret). |
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
| `GET` | `/api/v1/ca/spaces` | List spaces (`secret_ref` filters by a referenced secret). |
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
`pyppetdb import-puppet-ca` to migrate an existing Puppetserver CA. The import creates every
certificate from `signed/` through the CA service, skips certificates that are expired, not
issued by the imported CA, already present, or listed in the Puppet CA's `ca_crl.pem` (the CRL
itself is not imported), and exits non-zero when a certificate could not be processed. See
[Setup → Configure Certificate Authority](setup.md#2-configure-certificate-authority).
