# Architecture & Deployment Scenarios

This page describes common deployment scenarios for **pyppetdb** using Mermaid diagrams.

## 1. Full Proxy and Backend Architecture

In a standard deployment, pyppetdb acts as a high-performance middleware between your Puppet nodes and the traditional Puppet infrastructure (Puppetserver, PuppetDB).

```mermaid
graph TD
    subgraph "Managed Infrastructure"
        Node1[Puppet Node A]
        Node2[Puppet Node B]
        NodeN[Puppet Node ...]
    end

    LB[Load Balancer]

    subgraph "pyppetdb High Availability Cluster"
        P1[pyppetdb Instance 1]
        P2[pyppetdb Instance 2]
        P3[pyppetdb Instance N]
    end

    subgraph "State & Storage"
        DB[(MongoDB Cluster)]
    end

    subgraph "Legacy/Upstream Infrastructure (Optional)"
        PS[Puppetserver]
        PDB[PuppetDB]
    end

    Node1 & Node2 & NodeN --> LB
    LB --> P1 & P2 & P3
    P1 & P2 & P3 <--> DB
    P1 & P2 & P3 -- "Proxy & Cache" --> PS
    P1 & P2 & P3 -- "Proxy Queries" --> PDB
```

## 2. Catalog Caching & Redaction Flow

This diagram illustrates how pyppetdb offloads catalog requests and ensures sensitive data is redacted before reaching the node.

```mermaid
sequenceDiagram
    participant Node
    participant pyppetdb
    participant MongoDB
    participant Puppetserver

    Node->>pyppetdb: GET /puppet/v3/catalog/{node}
    pyppetdb->>MongoDB: Query Catalog Cache (TTL check)
    
    alt Cache Hit
        MongoDB-->>pyppetdb: Return Cached Catalog
        pyppetdb->>pyppetdb: Redact Secrets
        pyppetdb-->>Node: 200 OK (Cached Catalog)
    else Cache Miss
        pyppetdb->>Puppetserver: POST /puppet/v3/catalog/{node}
        Puppetserver-->>pyppetdb: Return Compiled Catalog
        pyppetdb->>MongoDB: Store Catalog in Cache
        pyppetdb->>pyppetdb: Redact Secrets
        pyppetdb-->>Node: 200 OK (Fresh Catalog)
    end
```

## 3. High-Availability Puppet CA

Unlike the standard Puppet CA which is often a single point of failure, pyppetdb allows any node in the cluster to handle CA operations by backing the certificate state in MongoDB.

```mermaid
graph LR
    subgraph "Nodes"
        N1[Node 1]
        N2[Node 2]
    end

    subgraph "pyppetdb CA Pool"
        CA1[pyppetdb CA Instance A]
        CA2[pyppetdb CA Instance B]
    end

    DB[(Shared MongoDB)]

    N1 -- "CSR / Cert Refresh" --> CA1
    N2 -- "CSR / Cert Refresh" --> CA2
    CA1 <--> DB
    CA2 <--> DB
```

## 4. Secure Job Execution (pyppetdb-agent)

The job execution engine uses a secure, bidirectional communication channel between the pyppetdb API and the agents.

```mermaid
graph RL
    subgraph "Management Layer"
        UI[Web UI / CLI]
        API[pyppetdb API]
        Hub[WebSocket Hub]
    end

    subgraph "Managed Node"
        Agent[pyppetdb Agent]
        Jobs[Pre-defined Job Scripts]
    end

    UI -- "Trigger Job" --> API
    API -- "Instruction" --> Hub
    Hub -- "Encrypted WS Message" --> Agent
    Agent -- "Validate & Execute" --> Jobs
    Agent -- "Real-time Log Stream" --> Hub
    Hub -- "Updates" --> UI
```
