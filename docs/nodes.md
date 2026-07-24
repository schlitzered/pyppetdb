# Nodes

A **Node** represents a Puppet-managed machine. pyppetdb collects each node's facts, catalogs and
reports as they flow through the Puppet and PuppetDB proxies, and exposes them through the
Management API under `/api/v1/nodes`.

All endpoints on this page require authentication (see [Administration](administration.md#authentication))
and are subject to RBAC. Non-admin users only see nodes that fall into a
[node group](#node-groups) attached to one of their teams.

## Node data

For each node pyppetdb stores:

* **Facts** — the node's reported facts, used for searching, grouping, RBAC and Hiera lookups.
* **Catalogs** — compiled catalogs, including exported resources. History retention is controlled
  by the `app_main_storeHistory_*` settings.
* **Reports** — Puppet run reports, including logs, metrics and resource events.

## Managing nodes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/nodes` | Search nodes (supports fact-based filtering, see below). |
| `GET` | `/api/v1/nodes/{node_id}` | Get a single node. |
| `POST` | `/api/v1/nodes/{node_id}` | Create a node. |
| `PUT` | `/api/v1/nodes/{node_id}` | Update a node. |
| `DELETE` | `/api/v1/nodes/{node_id}` | Delete a node. |
| `GET` | `/api/v1/nodes/_distinct_fact_values` | List the distinct values observed for a given fact. |
| `GET` | `/api/v1/nodes/_exported_resources` | Query exported resources across nodes. |
| `DELETE` | `/api/v1/nodes/_catalog_cache_wipe` | Invalidate cached catalogs (optionally scoped by facts). |

### Catalogs and reports

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/nodes/{node_id}/catalogs` | List stored catalogs for a node. |
| `GET` | `/api/v1/nodes/{node_id}/catalogs/{catalog_id}` | Get a specific catalog (secrets redacted). |
| `GET` | `/api/v1/nodes/{node_id}/reports` | List stored reports for a node. |
| `GET` | `/api/v1/nodes/{node_id}/reports/{report_id}` | Get a specific report. |

## Fact-based filtering

Several endpoints (node search, jobs, and node group rules) accept **complex filter** expressions
of the form:

```
<fact>:<operator>:<type>:<value>
```

* **operator:** `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `regex`
* **type:** `str`, `int`, `float`, `bool`

For example, to match nodes in the `production` environment with more than 4 CPUs:

```
environment:eq:str:production
processorcount:gt:int:4
```

## Node groups

**Node groups** map nodes to teams for RBAC purposes and are defined by fact-based rules.

* A group has one or more **filter rules**; each rule lists a `fact` and the `values` that match.
* Nodes matching a group's rules are associated with the group automatically.
* A group is attached to one or more **teams**, which grants those teams visibility of the matching
  nodes.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/nodes_groups` | Search node groups. |
| `GET` | `/api/v1/nodes_groups/{node_group_id}` | Get a node group. |
| `POST` | `/api/v1/nodes_groups/{node_group_id}` | Create a node group. |
| `PUT` | `/api/v1/nodes_groups/{node_group_id}` | Update a node group (rules and teams). |
| `DELETE` | `/api/v1/nodes_groups/{node_group_id}` | Delete a node group. |

This is the mechanism behind fact-based RBAC: for example, attaching a node group with the rule
`department = engineering` to the *engineering* team automatically grants that team access to every
node reporting `department=engineering`, including nodes that join later.

## pyppetdb instances

The `/api/v1/pyppetdb_nodes` endpoints expose the pyppetdb cluster members themselves (as tracked
by their heartbeats), not Puppet-managed nodes:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/pyppetdb_nodes` | List known pyppetdb instances. |
| `GET` | `/api/v1/pyppetdb_nodes/{node_id}` | Get a single pyppetdb instance. |
| `DELETE` | `/api/v1/pyppetdb_nodes/{node_id}` | Remove a stale pyppetdb instance record. |
