# Administration

This page covers users, authentication, teams and the RBAC model that controls access to the
Management API.

## Authentication

The Management API accepts two authentication methods:

* **Session** — a browser session established through OAuth login (`/oauth/...`) or the
  `/api/v1/authenticate` endpoint. Backed by a signed session cookie (`app_secretkey`).
* **API credentials** — a secret-id / secret pair sent as request headers, used for
  automation and CLI access:

  ```
  x-secret-id: <credential_id>
  x-secret:    <credential_secret>
  ```

The `/api/v1/authenticate` endpoint reports the current user (`GET`), logs in (`POST`) and logs out
(`DELETE`).

## The first admin user

Bootstrap the first administrator with the CLI (it cannot be created through the API before any user
exists):

```bash
pyppetdb create-admin --user-id admin --email admin@example.com --name "System Admin"
```

If `--password` is omitted a random password is generated and printed once. See
[Setup → Create Administrative User](setup.md#1-create-administrative-user).

## Users

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/users` | Search users. |
| `GET` | `/api/v1/users/{user_id}` | Get a user. |
| `POST` | `/api/v1/users/{user_id}` | Create a user. |
| `PUT` | `/api/v1/users/{user_id}` | Update a user. |
| `DELETE` | `/api/v1/users/{user_id}` | Delete a user. |

A user has an `email`, `name`, a `backend` (local or an OAuth provider) and an `admin` flag.
**Admin users bypass all permission checks** and can see all nodes.

### API credentials

Each user can own multiple long-lived API credentials (used with the `x-secret-id` / `x-secret`
headers). The secret is returned **only once**, at creation time.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/users/{user_id}/credentials` | List a user's credentials. |
| `POST` | `/api/v1/users/{user_id}/credentials` | Create a credential (returns the secret once). |
| `GET` | `/api/v1/users/{user_id}/credentials/{credential_id}` | Get credential metadata. |
| `PUT` | `/api/v1/users/{user_id}/credentials/{credential_id}` | Update a credential's description. |
| `DELETE` | `/api/v1/users/{user_id}/credentials/{credential_id}` | Delete a credential. |

## Teams

Permissions are never assigned to users directly — they are assigned to **teams**, and users become
members of teams. Team membership can be maintained manually (`users` list) or synchronized from an
LDAP group (`ldap_group`, requires the `ldap_*` configuration).

A team has:

* `users` — member user IDs.
* `ldap_group` — optional LDAP group whose members are synchronized into the team.
* `permissions` — the permission strings granted to members.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/teams` | Search teams. |
| `GET` | `/api/v1/teams/{team_id}` | Get a team. |
| `POST` | `/api/v1/teams/{team_id}` | Create a team. |
| `PUT` | `/api/v1/teams/{team_id}` | Update a team (members and permissions). |
| `DELETE` | `/api/v1/teams/{team_id}` | Delete a team. |

## Permissions

A user is authorized for an action if **any** team they belong to holds the required permission.
Admin users are always authorized.

Two kinds of node visibility / action control combine:

1. **Operation permissions** — control *which actions* a team may perform (see below).
2. **Fact-based node access** — controls *which nodes* a team can see, via
   [node groups](nodes.md#node-groups) attached to the team.

### Static vs. dynamic permissions

* **Static permissions** are a fixed set of operation permissions, formatted as
  `DOMAIN:SUBDOMAIN::ACTION`, for example:

    * `NODES::CREATE`, `NODES::UPDATE`, `NODES::DELETE`
    * `TEAMS::GET`, `USERS::CREATE`, `USERS:CREDENTIALS::CREATE`
    * `HIERA:KEYS::CREATE`, `HIERA:LEVEL_DATA::UPDATE`
    * `CA:AUTHORITIES::CREATE`, `CA:SPACES::UPDATE`
    * `JOBS::GET`, `JOBS:JOB::CREATE`, `JOBS:DEFINITION::CREATE`

* **Dynamic permissions** are scoped to a specific resource id, allowing fine-grained grants:

    * `JOBS:JOB:{definition_id}:CREATE` — run one specific job definition.
    * `HIERA:LEVEL_DATA:{key_id}:CREATE|UPDATE|DELETE` — write data for one specific Hiera key.
    * `CA:AUTHORITIES:{ca_id}:CERTS:UPDATE` — manage certs of one authority.
    * `CA:SPACES:{space_id}:CERTS:UPDATE` — manage certs of one space.

You can discover the full set of currently valid permission strings (static plus the dynamic ones
derived from existing definitions, keys, authorities and spaces) via:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/permissions` | List all assignable static and dynamic permissions. |

## LDAP integration

When `ldap_url` (and the required `ldap_binddn` / `ldap_password`) is configured, teams with an
`ldap_group` set have their membership synchronized from the directory, so access follows your
existing group management. See the
[Configuration Reference → LDAP](configuration_reference.md#ldap-ldap_).
