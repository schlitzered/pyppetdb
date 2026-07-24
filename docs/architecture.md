# Architecture & Deployment Scenarios

This page describes how **pyppetdb** is structured internally and the common ways to deploy it.

## 1. Component Overview

pyppetdb is a **single FastAPI application**. It exposes three independent router groups that
are toggled individually via configuration flags:

| Router group | Enable flag | URL prefixes | Purpose |
|--------------|-------------|--------------|---------|
| Management API | `app_main_enable` | `/api`, `/oauth` | REST API for users, web UI, and inter-instance communication |
| Puppet Proxy | `app_puppet_enable` | `/puppet`, `/puppet-ca` | Puppetserver front-end and Puppet CA implementation |
| PuppetDB Proxy | `app_puppetdb_enable` | `/pdb` | PuppetDB command/query endpoints |

!!! important "One process listens on exactly one port"
    Regardless of which router groups are enabled, a pyppetdb process always binds to a single
    address/port pair (`app_main_host` / `app_main_port`) and uses a single TLS configuration
    (`app_main_ssl_*`). You do **not** configure a separate port per router group.

    To separate concerns across ports (e.g. terminate Puppet agent mTLS on `:8140` while serving
    the management UI on `:8000`), run **multiple pyppetdb processes** — each with a different set
    of `*_enable` flags and a different `app_main_port` — all backed by the same MongoDB. For
    small setups you can also run a single all-in-one process with every router group enabled.

```mermaid
graph TD
    subgraph "Clients"
        User[Human / CLI / Web UI]
        Agent[Puppet Agent]
        PS[Puppetserver]
    end

    subgraph "pyppetdb processes (share one MongoDB)"
        MGMT["Management instance<br/>app_main_enable=true<br/>:8000"]
        PUP["Puppet proxy instance<br/>app_puppet_enable=true<br/>:8140 (mTLS)"]
        PDB["PuppetDB proxy instance<br/>app_puppetdb_enable=true<br/>:8002 (mTLS)"]
    end

    subgraph "Backends"
        UPS_PS[Upstream Puppetserver]
        UPS_PDB[Upstream PuppetDB]
        DB[(MongoDB Replica Set)]
    end

    User --> MGMT
    Agent --> PUP
    PS --> PDB
    PUP -. optional forward .-> UPS_PS
    PDB -. optional forward .-> UPS_PDB
    MGMT & PUP & PDB <--> DB
```

## 2. Agent Interaction & Data Flow

From a Puppet Agent's perspective, the Puppet proxy instance is the entry point for both
certificate management and catalog compilation. The agent authenticates via mTLS; pyppetdb
validates the client certificate against its own CA records before proxying (see
`app_main_ssl_*` and `ca_verifyCertificateRegistration`).

```mermaid
graph LR
    Node[Puppet Agent]
    P1["pyppetdb<br/>Puppet proxy :8140"]
    UPS[Upstream Puppetserver]
    DB[(MongoDB)]

    Node -- "1. CSR / cert (/puppet-ca/v1)" --> P1
    Node -- "2. Catalog (/puppet/v3/catalog)" --> P1
    P1 -- "3. Proxy compile" --> UPS
    UPS -- "4. Compiled catalog" --> P1
    P1 -- "5. Store facts / catalog" --> DB
    P1 -- "6. Return catalog" --> Node
```

## 3. Secret Redaction Strategy

Redaction is applied at read time in the **Management API**. The Puppet Agent needs the
unredacted catalog to configure the system, while humans and API consumers only ever see
redacted data. Redaction happens even for deeply nested values and for job logs.

```mermaid
sequenceDiagram
    participant Node as Puppet Agent
    participant P1 as pyppetdb Puppet proxy
    participant PS as Upstream Puppetserver
    participant DB as MongoDB
    participant API as pyppetdb Management API
    participant User as Human / UI

    Note over Node, PS: Catalog Compilation
    Node->>P1: GET /puppet/v3/catalog
    P1->>PS: Proxy request
    PS-->>P1: Compiled catalog (full secrets)
    P1->>DB: Store catalog (full secrets)
    P1-->>Node: Return catalog (full secrets)

    Note over API, User: API Consumption
    User->>API: GET /api/v1/nodes/{node}/catalogs/{id}
    API->>DB: Fetch catalog
    DB-->>API: Raw catalog
    API->>API: Redact secrets
    API-->>User: Redacted catalog
```

## 4. Secure Job Execution (Inter-Instance WebSocket)

The pyppetdb agent connects to a Puppet proxy instance over a WebSocket. When a user triggers a
job on the Management API, the target agent may be connected to a *different* pyppetdb instance.
pyppetdb instances form a mesh and relay the instruction over an internal WebSocket channel
(`app_main_interApiIdleTimeout` controls its idle timeout) to the instance that holds the agent
connection.

```mermaid
graph TD
    User[Human / UI]
    API["pyppetdb<br/>Management API"]
    WS[Inter-instance WebSocket mesh]
    Proxy["pyppetdb<br/>Puppet proxy"]
    Agent[pyppetdb agent]

    User -- "Trigger job (/api/v1/jobs/jobs)" --> API
    API -- "Relay instruction" --> WS
    WS -- "Deliver to owning instance" --> Proxy
    Proxy -- "WebSocket" --> Agent
    Agent -- "Execute pre-defined job" --> Jobs[Pre-defined executables]
    Agent -. "Stream logs back" .-> Proxy
```

## 5. Storage

pyppetdb stores all state in **MongoDB** and requires a **replica set**, because it relies on
[change streams](https://www.mongodb.com/docs/manual/changeStreams/) to react to data changes
in real time (cache invalidation, inter-instance coordination, live job logs) instead of
polling. See the [Setup](setup.md#mongodb-setup) guide for details. Shard-capable collections
can be distributed using placement facts (`mongodb_placementFacts`).
