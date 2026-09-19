# ComfyCluster

**ComfyCluster is a Windows-first desktop app, fleet manager, and scheduler for ComfyUI.**

The goal is to make several GPU workstations behave like one managed Comfy resource pool without turning artists or operators into cluster administrators.

> Current status: working early prototype. The Windows desktop, background agent, and controller are packaged as standalone executables. Agents discover GPUs and ComfyUI, launch one worker per GPU, report live capabilities, inventory models/custom nodes, and execute workflows through a global compatibility-aware scheduler. The controller persists jobs, fleet state, desired releases, host drain state, users, groups, memberships, and API credentials.

## Product shape

A normal Windows workstation gets two ComfyCluster components:

```text
ComfyCluster.exe
  User-facing desktop application
  Home / Comfy / Models / Nodes / Outputs / Cluster / Settings
        |
        | localhost only
        v
comfycluster-agent.exe
  Background Scheduled Task
  GPU discovery, Comfy lifecycle, inventory, jobs
        |
        | outbound authenticated WebSocket
        v
ComfyCluster Controller
  Desired state, fleet inventory, scheduling, releases, tenancy
        |
        +---- Windows PC 1 -> GPU 0 / GPU 1
        +---- Windows PC 2 -> GPU 0 / GPU 1
        +---- Windows PC 3 -> GPU 0 / GPU 1
```

Closing `ComfyCluster.exe` does not stop local Comfy workers or remove the machine from the cluster. The agent keeps running in the background.

Kubernetes may become a runtime for larger Linux deployments later, but it is not required. Native Windows is the first target.

## Enterprise tenancy and privacy

ComfyCluster treats creative teams as private groups rather than one shared queue and output namespace.

- every human job is owned by a user and group
- output/workflow metadata inherits the job's privacy scope
- group jobs are visible only to members of that group
- private jobs are visible only to the submitting user
- platform administrators can inspect queue metadata without automatically receiving workflow/output content access
- machine agent credentials are separate from human API credentials
- user API tokens are revocable and stored as hashes in the controller database

The platform administrator bootstrap token is generated separately from the agent token during controller installation.

## Resource governance

The global scheduler now includes the first multi-tenant controls needed to keep a busy creative enterprise usable:

- per-user maximum queued jobs
- per-user maximum running jobs
- per-group maximum queued jobs
- per-group maximum running jobs
- weighted fair scheduling between backlogged groups
- compatibility-aware worker selection still applies after tenant scheduling
- queue-limit responses return explicit `429 queue_limit_reached` details rather than accepting an unbounded backlog

A group's weight controls its relative share when multiple groups remain backlogged. Idle capacity can still be used by any eligible group when others have no runnable work.

## Desktop application

The first desktop build is intentionally modeled after the local-first package-management experience of tools like Stability Matrix, but focused only on ComfyUI and the cluster.

Implemented screens:

- **Home**: local GPU/VRAM state, cluster connection, Production Comfy summary, one worker per GPU, Start/Stop/Restart, Drain/Resume, Open ComfyUI
- **Comfy**: detected environment, Comfy version/commit/Python, desired fleet release, drift state, inventory refresh
- **Models**: cluster model inventory, size/category, whether the model is on this PC, host availability
- **Custom Nodes**: local commit, host coverage, basic consistency view
- **Outputs**: recent authorized cluster jobs and output metadata
- **Cluster**: registered Windows hosts and their GPU workers, connectivity and drain state
- **Settings**: controller/local-agent endpoints and direct controller-admin access

The desktop uses the local agent API on `127.0.0.1:9321` for workstation controls, so Start/Stop/Restart remains available if the central controller is temporarily unavailable. Fleet policy such as Drain/Resume remains controller-owned.

## Windows deployment

Controller installs generate two different bootstrap credentials:

```text
COMFYCLUSTER_AGENT_TOKEN   machine-to-controller authentication
COMFYCLUSTER_ADMIN_TOKEN   human/API platform administration
```

Do not reuse the machine credential as a human credential.

Once a user token has been issued by the admin API, it can be provisioned to a workstation desktop:

```powershell
.\install-agent.ps1 `
  -ControllerUrl "wss://CONTROLLER/api/v1/agents/ws" `
  -AgentToken "MACHINE-TOKEN" `
  -UserToken "USER-TOKEN"
```

The desktop sends the user token only to controller HTTP APIs. The background agent continues using the separate agent credential.

## Tenancy API

Platform-admin bootstrap requests use:

```text
Authorization: Bearer <COMFYCLUSTER_ADMIN_TOKEN>
```

Important endpoints:

- `GET /api/v1/me`
- `GET /api/v1/groups`
- `GET /api/v1/queue/summary`
- `POST /api/v1/admin/groups`
- `POST /api/v1/admin/users`
- `POST /api/v1/admin/memberships`
- `POST /api/v1/admin/users/{user_id}/tokens`
- `DELETE /api/v1/admin/tokens/{token_id}`
- `GET /api/v1/admin/jobs` returns operational summaries without workflow/output content
- `GET /api/v1/jobs` returns only content the authenticated user is allowed to see

## Implemented agent and controller foundations

### Windows agent

- NVIDIA discovery through `nvidia-smi`, including stable GPU UUIDs
- mock-GPU mode for development without NVIDIA hardware
- ComfyUI discovery, including common portable/venv layouts and Stability Matrix installs
- one logical Comfy worker per physical GPU
- native worker launch using `--cuda-device` and unique ports
- start, stop, restart, health probing, process supervision, and per-worker logs
- localhost desktop-control API bound to `127.0.0.1` by default
- automatic reconnect to the controller
- authenticated outbound WebSocket connection
- Comfy `/prompt` submission, history polling, cancellation, and output metadata reporting
- custom-node and model inventory, including `extra_model_paths.yaml`
- live `/object_info` capability discovery so each worker reports the node types it can actually execute
- optional official `comfy-cli` discovery using its structured `comfy discover` contract

### Controller

- FastAPI control plane
- host/GPU/worker inventory and disconnect handling
- cluster model and custom-node availability matrices
- global tenant-aware job queue with worker reservations
- compatibility-aware scheduling using connectivity, worker state, VRAM, models, and live registered Comfy node types
- weighted fair group scheduling and concurrency limits
- user/group tenancy, memberships, hashed API credentials, and scoped job visibility
- optional SQLite persistence and restart recovery behavior
- desired release and drift planning
- host drain/resume behavior

## Design principles

1. **The controller owns desired state, authorization, quotas, and scheduling.**
2. **The Windows agent owns local process/GPU supervision.**
3. **Machine identity and human identity are separate security boundaries.**
4. **Infrastructure administration does not automatically grant content access.**
5. **Comfy itself remains the execution engine.**
6. **Models are data, not application releases.**
7. **Workers advertise runtime truth.**
8. **A worker should require no inbound management port.**

## Near-term priorities

1. desktop sign-in/token management and group-aware queue UI
2. central output asset storage with the same authorization rules as jobs
3. SSO/OIDC integration so enterprises do not have to manually provision long-lived user tokens
4. group administration UI, audit log, and usage accounting
5. canary release reconciliation and rollback
6. model synchronization with hashing and integrity verification
7. cluster-level Comfy API v2-compatible surface
8. unified Comfy workspace and cluster-aware MCP

## License

MIT.
