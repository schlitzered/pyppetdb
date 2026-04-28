# Introduction

Welcome to **pyppetdb**, a high-performance, modular replacement and enhancement for various
components of the Puppet infrastructure.

Originally conceived as a lightweight replacement for PuppetDB, pyppetdb has evolved into a
versatile middleware layer that sits between your Puppet nodes, Puppetservers, and PuppetDB.
It is designed to improve scalability and reliability across your entire Puppet fleet.

## Core Architecture

pyppetdb can be deployed in several configurations:

*   **PuppetDB Proxy/Replacement**: It implements basic PuppetDB endpoints. While it doesn't
    natively answer complex PuppetDB queries, it offers a dedicated, modern FastAPI-based API.
    It can optionally forward requests to an existing PuppetDB instance if those capabilities
    are required.
*   **Front-end for Puppetserver**: pyppetdb can sit in front of a Puppetserver to offload
    "expensive" but simple tasks. By serving static file content directly from disk, it frees
    up Puppetserver processes to focus exclusively on heavy catalog compilation.

## Key Features

### Intelligent Catalog Caching
pyppetdb provides a sophisticated catalog caching layer. Unlike the native Puppetserver cache,
which is limited to environment or node-level wipes, pyppetdb allows for **fact-based cache
invalidation**. This enables granular control—for example, invalidating catalogs only for nodes
that match specific facts affected by a code change. Catalogs also feature automatic
TTL-based expiration.

### High-Availability Puppet CA
pyppetdb implements the Puppet CA API, including the undocumented automatic certificate refresh
endpoints.
*   **Fault Tolerance**: Unlike the standard single-node Puppet CA, pyppetdb allows *every* node
    in the cluster to act as a CA.
*   **Database-Backed**: By storing CA data in a central database rather than a flat filesystem,
    you eliminate the need for complex shared storage or `keepalived` failover setups.

### PyHiera: Validated Hiera Backend
pyppetdb includes a powerful Hiera backend powered by PyHiera.
*   **Data Validation**: Define custom key models using Pydantic-based plugins or dynamic
    JSON-schema-like definitions. This ensures that data stored and returned during lookups
    is structurally valid.
*   **Performance**: The engine handles heavy merging and caching logic, relieving the
    Puppetserver of these tasks. The cache is automatically invalidated the moment data in
    a Hiera level is modified.

### Fact-Based RBAC
pyppetdb implements a dynamic Role-Based Access Control (RBAC) system.
*   **Dynamic Access**: Permissions are granted to **Teams** (which contain **Users**) based on
    the **Facts** of a node.
*   **Granular Control**: This allows for automated, environment-aware access management—for
    example, automatically giving a specific team access to all nodes where `department=engineering`.

### Advanced Secrets Redaction
To maintain a high security posture, pyppetdb can automatically redact sensitive information.
*   **Deep Redaction**: Secrets (e.g., extracted from `eyaml`) can be stored encrypted in pyppetdb.
    It will then redact these secrets from stored catalogs and reports, even if they are deeply
    nested in dictionaries or if the `Secret` keyword was omitted in the manifest.
*   **Log Safety**: Redaction is applied globally, including to real-time **job logs**, ensuring
    that sensitive data never leaks into the UI or monitoring tools.

### Secure Job Execution Engine
Control your infrastructure via the optional **pyppetdb agent**.
*   **Security-First**: To prevent arbitrary command execution, jobs must be defined on both the
    agent and the server.
*   **Validation**: Every environment variable and parameter is validated (type checking, bounds
    checking, enums) to prevent shell injection attacks.
*   **Real-time Logs**: Logs are streamed from agents to the pyppetdb API in real-time, providing
    a "GitHub Actions-like" experience for monitoring job progress.
