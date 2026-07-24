# Jobs

The jobs engine lets you run pre-defined commands on nodes via the optional **pyppetdb agent**,
with real-time log streaming back to the API — a "GitHub Actions-like" experience.

The design is **security-first**: a job can only run a command that is defined *both* on the server
(as a **job definition**) and on the agent. Every parameter and environment variable is validated
against the definition (type, bounds, regex, enum) before execution, which prevents arbitrary
command and shell injection.

## Installing the pyppetdb agent

!!! note "To be documented"
    This section will describe how to install and configure the `pyppetdb_agent` on managed nodes
    (installation, connecting the agent to a pyppetdb instance, and registering local job
    definitions).

    *Placeholder — content to follow.*

## Job definitions

A **job definition** describes a single executable and the parameters/environment it accepts. It is
managed on the server and must have a matching definition on the agent.

Fields:

* `id` — definition identifier.
* `executable` — the command/executable to run.
* `user` / `group` — the OS user and group to run as.
* `params_template` — ordered list describing how parameters are passed to the executable.
* `params` — map of named parameter definitions.
* `environment_variables` — map of named environment-variable definitions.

Each parameter / environment-variable definition constrains its input:

| Field | Meaning |
|-------|---------|
| `type` | One of `string`, `int`, `float`, `bool`, `enum`. |
| `regex` | Optional regex the value must match. |
| `min` / `max` | Optional bounds for numeric values. |
| `options` | Allowed values for `enum`. |

### Managing definitions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jobs/definitions` | List job definitions. |
| `POST` | `/api/v1/jobs/definitions` | Create a job definition. |
| `GET` | `/api/v1/jobs/definitions/{definition_id}` | Get a job definition. |
| `PUT` | `/api/v1/jobs/definitions/{definition_id}` | Update a job definition. |
| `DELETE` | `/api/v1/jobs/definitions/{definition_id}` | Delete a job definition. |

## Running jobs

A **job** is one execution of a definition against a set of nodes. Nodes are selected with a
fact-based `node_filter` (the same `<fact>:<operator>:<type>:<value>` syntax used in
[node search](nodes.md#fact-based-filtering)). The number of matched nodes may not exceed
`jobs_maxNodesPerJob`.

When a job is created it fans out into per-node executions. Job records and their logs expire after
`jobs_expireSeconds`.

A job carries:

* `definition_id` — the job definition to run.
* `parameters` — values for the definition's parameters (validated against it).
* `env_vars` — values for the definition's environment variables (validated against it).
* `node_filter` — fact-based selection of target nodes.

### Managing jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jobs/jobs` | List jobs. |
| `POST` | `/api/v1/jobs/jobs` | Create (trigger) a job. |
| `GET` | `/api/v1/jobs/jobs/{job_id}` | Get a job. |
| `POST` | `/api/v1/jobs/jobs/{job_id}/cancel` | Cancel a running job. |

### Per-node executions and logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jobs/nodes_jobs` | List per-node job executions. |
| `GET` | `/api/v1/jobs/nodes_jobs/{node_job_id}` | Get a single per-node execution. |
| `GET` | `/api/v1/jobs/nodes_jobs_logs/{log_id}` | Retrieve the log for a per-node execution. |

Logs are streamed from the agent through pyppetdb to the API in real time (see
[Architecture → Secure Job Execution](architecture.md#4-secure-job-execution-inter-instance-websocket)).
Secret redaction is applied to job logs as well, so secrets never leak into the UI.

## Concurrency and queueing

Each agent reports a concurrency limit (its `max_jobs`) to the server. pyppetdb dispatches per-node
executions to an agent only while it has a free slot; any excess stays `scheduled` in the queue and
is dispatched automatically, oldest-first, as running jobs finish and slots free up. Agents are
never overloaded, and no job is silently dropped.

!!! warning "Queue wait is bounded by `jobs_expireSeconds`"
    A per-node execution that waits in the `scheduled` state longer than `jobs_expireSeconds`
    (default 3600) is marked `failed` by the expiry worker. If you expect long queues, raise
    `jobs_expireSeconds` accordingly.

## Permissions

Triggering jobs is governed by RBAC. In addition to the static `JOBS:JOB::CREATE` permission, each
definition has a dynamic permission `JOBS:JOB:{definition_id}:CREATE`, so you can grant a team the
right to run one specific definition without granting all of them. See
[Administration → Permissions](administration.md#permissions).
