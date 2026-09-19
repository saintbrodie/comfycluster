# ComfyCluster

**ComfyCluster is a Windows-first fleet manager and scheduler for ComfyUI.**

The goal is to make several GPU workstations behave like one managed Comfy resource pool without turning the user into a cluster administrator.

> Current status: working early prototype. Windows agents can discover GPUs and ComfyUI, launch one worker per GPU, register with a central controller, report live Comfy capabilities, and execute workflows through a global compatibility-aware scheduler. The controller has a web dashboard, durable SQLite option, job lifecycle tracking, model/custom-node inventory, and release-drift groundwork.

## Architecture

```text
                         ComfyCluster
                              |
                +-------------+-------------+
                |                           |
          Unified Comfy UI             Agent / MCP
                |                           |
                +-------------+-------------+
                              |
                         Controller
                    /         |         \
                   /          |          \
               PC 1          PC 2        PC 3
              GPU0/1        GPU0/1      GPU0/1
```

Each Windows workstation runs a lightweight outbound agent. The agent discovers NVIDIA GPUs and manages one long-lived ComfyUI process per GPU. The controller owns fleet inventory, desired state, job scheduling, compatibility decisions, and centralized status.

Kubernetes may become a runtime for larger Linux deployments later, but it is not required. Native Windows is the first target.

## Implemented

### Windows agent

- NVIDIA discovery through `nvidia-smi`, including stable GPU UUIDs
- mock-GPU mode for development without NVIDIA hardware
- ComfyUI discovery, including common portable/venv layouts and Stability Matrix installs
- one logical Comfy worker per physical GPU
- native worker launch using `--cuda-device` and unique ports
- start, stop, restart, health probing, process supervision, and per-worker logs
- automatic reconnect to the controller
- Comfy `/prompt` submission, history polling, cancellation, and output metadata reporting
- custom-node and model inventory, including `extra_model_paths.yaml`
- live `/object_info` capability discovery so each worker reports the node types it can actually execute
- optional official `comfy-cli` discovery using its structured `comfy discover` contract
- PyInstaller Windows executable build and Scheduled Task install/uninstall scripts

### Controller

- FastAPI control plane and dark web dashboard
- outbound-agent WebSocket protocol
- host/GPU/worker inventory and disconnect handling
- cluster model and custom-node availability matrices
- global job queue with worker reservations
- job dispatch, completion, failure, cancellation, and output tracking
- optional SQLite persistence and restart recovery behavior
- release manifest comparison for Comfy commit, node commit, and model drift
- workflow requirement analysis for node types and model references
- compatibility-aware scheduling using connectivity, worker state, VRAM, models, and live registered Comfy node types
- per-worker compatibility explanations such as `missing_models`, `missing_node_types`, and `insufficient_vram`

### Official Comfy tooling integration

ComfyCluster is intentionally a control plane around Comfy rather than a fork of it.

The first `comfy-cli` adapter supports:

- `comfy discover` capability/version negotiation
- `comfy node deps-in-workflow`
- `comfy node save-snapshot`
- `comfy update comfy --version ...`

The longer-term public execution surface should follow official Comfy API v2 semantics, and cluster-aware MCP is planned on top of the same controller.

## Development demo

Python 3.11+ is currently required for a source checkout.

```powershell
./scripts/install-dev.ps1
./scripts/dev-demo.ps1
```

Or start the controller manually:

```powershell
.\.venv\Scripts\comfycluster-controller.exe serve --database .\comfycluster.db
```

Then in another terminal:

```powershell
.\.venv\Scripts\comfycluster-agent.exe run --mock-gpus 2
```

Open `http://127.0.0.1:9320`.

On a real Comfy machine:

```powershell
$env:COMFYCLUSTER_COMFY_HOME = "D:\AI\ComfyUI"
.\.venv\Scripts\comfycluster-agent.exe run --controller ws://CONTROLLER:9320/api/v1/agents/ws
```

If `comfy-cli` is installed somewhere other than `PATH`:

```powershell
$env:COMFYCLUSTER_COMFY_CLI_EXECUTABLE = "C:\path\to\comfy.exe"
```

## Useful API endpoints

- `GET /api/v1/health`
- `GET /api/v1/hosts`
- `GET /api/v1/workers`
- `GET /api/v1/models`
- `GET /api/v1/nodes`
- `POST /api/v1/workflows/analyze`
- `POST /api/v1/workflows/compatibility`
- `POST /api/v1/releases/compare`
- `POST /api/v1/hosts/{host}/commands/{action}`
- `GET /api/v1/jobs`
- `POST /api/v1/jobs`
- `POST /api/v1/jobs/{job}/cancel`
- `WS /api/v1/agents/ws`

A submitted job contains an API-format Comfy workflow. The scheduler analyzes the graph before dispatch and only selects an eligible worker when capability information is available.

## Design principles

1. **The controller owns desired state and scheduling.**
2. **The Windows agent owns local process/GPU supervision.**
3. **Comfy itself remains the execution engine.**
4. **Official Comfy tooling handles Comfy-specific package mechanics wherever practical.**
5. **Models are data, not application releases.** Large model synchronization is managed separately from Comfy/custom-node releases.
6. **Workers advertise runtime truth.** `/object_info`, model inventory, GPU state, and management-tool capability determine eligibility.
7. **A worker should require no inbound management port.** The agent maintains the outbound controller connection.

## Near-term priorities

1. make a repeatable three-PC Windows deployment and upgrade flow
2. finish `comfy-cli` desired-state/release reconciliation and canary rollback
3. add controller-triggered model synchronization with hashing and integrity verification
4. add secure agent enrollment and controller authentication
5. add retries/draining and stronger failure recovery
6. expose a cluster-level Comfy API v2-compatible surface
7. serve one unified Comfy workspace backed by the global scheduler
8. add cluster-aware MCP and gated agentic administration

See [docs/architecture.md](docs/architecture.md) and [docs/roadmap.md](docs/roadmap.md).

## Prior art

ComfyCluster is deliberately borrowing proven ideas from SwarmUI, ComfyDeploy, distributed Comfy schedulers, Stability Matrix, Salad's Comfy API wrapper, the Windows Comfy portable installer ecosystem, and official Comfy projects such as `comfy-cli`, `comfy-api-proxy`, and `comfy-mcp`.

## License

MIT.
