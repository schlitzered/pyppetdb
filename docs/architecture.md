# Architecture & Deployment Scenarios

This page describes common deployment scenarios and data flows for **pyppetdb**.

## 1. Component Overview

pyppetdb consists of three primary functional components, typically listening on different ports:

*   **Puppet API Proxy (Port 8001)**: Handles Puppetserver and CA replacement/proxying.
*   **PuppetDB API Proxy (Port 8002)**: Handles PuppetDB query proxying.
*   **Management API (Port 8000)**: The main REST API for users, frontends, and inter-service communication.

```mermaid
graph TD
    subgraph "External Access"
        User[Human / CLI / Web UI]
        Agent[Puppet Agent]
    end

    subgraph "Ingress Layer"
        Proxy[Apache / Nginx]
    end

    subgraph "pyppetdb Service"
        direction TB
        API_8000[Management API :8000]
        Proxy_8001[Puppet Proxy :8001]
        PDB_8002[PuppetDB Proxy :8002]
    end

    subgraph "Backend Infrastructure"
        PS[Puppetserver]
        PDB[PuppetDB]
        DB[(MongoDB)]
    end

    User --> Proxy --> API_8000
    Agent --> Proxy_8001
    Proxy_8001 --> PS
    PS --> PDB_8002
    PDB_8002 --> PDB
    API_8000 & Proxy_8001 & PDB_8002 <--> DB
```

## 2. Agent Interaction & Data Flow

From the perspective of a Puppet Agent, pyppetdb acts as the entry point for both catalog compilation and data submission. Note that the Puppetserver must be co-located or accessible to the Puppet Proxy.

```mermaid
graph LR
    Node[Puppet Agent]
    P1[pyppetdb :8001<br/>Puppet Proxy]
    PS[Puppetserver]
    P2[pyppetdb :8002<br/>PuppetDB Proxy]
    PDB[PuppetDB]

    Node -- "1. Catalog/Cert" --> P1
    P1 -- "2. Proxy" --> PS
    PS -- "3. Store Facts/Catalog" --> P2
    P2 -- "4. Optional Forward" --> PDB
```

## 3. Secret Redaction Strategy

Redaction is applied at the **Management API** level. The Puppet Agent requires unredacted secrets to configure the system, while humans and external consumers of the API see redacted data.

```mermaid
sequenceDiagram
    participant Node as Puppet Agent
    participant P1 as pyppetdb :8001
    participant PS as Puppetserver
    participant DB as MongoDB
    participant API as pyppetdb :8000
    participant User as Human / UI

    Note over Node, PS: Catalog Compilation
    Node->>P1: GET /puppet/v3/catalog
    P1->>PS: Proxy Request
    PS-->>P1: Compiled Catalog (Full Secrets)
    P1->>DB: Store Catalog (Full Secrets)
    P1-->>Node: Return Catalog (Full Secrets)
    
    Note over API, User: API Consumption
    User->>API: GET /api/v1/nodes/{node}/catalog
    API->>DB: Fetch Catalog
    DB-->>API: Return Raw Catalog
    API->>API: Redact Secrets
    API-->>User: Return Redacted Catalog
```

## 4. Secure Job Execution (Inter-API WebSocket)

When a user triggers a job, the request traverses the management API and uses an internal WebSocket channel to reach the specific pyppetdb instance managing the agent connection.

```mermaid
graph TD
    User[Human / UI]
    API[pyppetdb :8000<br/>Management API]
    WS[Inter-API WebSocket]
    Proxy[pyppetdb :8001<br/>Puppet Proxy]
    Agent[pyppetdb-agent]

    User -- "Trigger Job" --> API
    API -- "Instruction" --> WS
    WS -- "Relay" --> Proxy
    Proxy -- "WebSocket" --> Agent
    Agent -- "Execute Job" --> Jobs[Pre-defined Scripts]
```
