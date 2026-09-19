# ComfyCluster

**ComfyCluster is a Windows-first desktop app, fleet manager, and scheduler for ComfyUI.**

The goal is to make several GPU workstations behave like one managed Comfy resource pool without turning artists or operators into cluster administrators.

> Current status: working early prototype. The Windows desktop, background agent, and controller are all packaged as standalone executables. Agents can discover GPUs and ComfyUI, launch one worker per GPU, report live capabilities, inventory models/custom nodes, and execute workflows through a global compatibility-aware scheduler. The controller persists jobs, fleet state, desired releases, and host drain state.

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
  Desired state, fleet inventory, scheduling, releases
        |
        +---- Windows PC 1 -> GPU 0 / GPU 1
        +---- Windows PC 2 -> GPU 0 / GPU 1
        +---- Windows PC 3 -> GPU 0 / GPU 1
```

Closing `ComfyCluster.exe` does not stop local Comfy workers or remove the machine from the cluster. The agent keeps running in the background.

Kubernetes may become a runtime for larger Linux deployments later, but it is not required. Native Windows is the first target.

## Desktop application

The first desktop build is intentionally modeled after the local-first package-management experience of tools like Stability Matrix, but focused only on ComfyUI and the cluster.

Implemented screens:

- **Home**: local GPU/VRAM state, cluster connection, Production Comfy summary, one worker per GPU, Start/Stop/Restart, Drain/Resume, Open ComfyUI
- **Comfy**: detected environment, Comfy version/commit/Python, desired fleet release, drift state, inventory refresh
- **Models**: cluster model inventory, size/category, whether the model is on this PC, host availability
- **Custom Nodes**: local commit, host coverage, basic consistency view
- **Outputs**: recent cluster jobs and output metadata
- **Cluster**: all registered Windows hosts and their GPU workers, connectivity and drain state
- **Settings**: controller/local-agent endpoints and direct controller-admin access

The desktop uses the local agent API on `127.0.0.1:9321` for workstation controls, so Start/Stop/Restart remains available if the central controller is temporarily unavailable. Fleet policy such as Drain/Resume remains controller-owned.

## Implemented

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
- PyInstaller Windows executable build and Scheduled Task install/uninstall scripts

### Controller

- FastAPI control plane and web admin dashboard
- outbound-agent WebSocket protocol
- host/GPU/worker inventory and disconnect handling
- persistent host Drain/Resume state
- cluster model and custom-node availability matrices
- global job queue with worker reservations
- job dispatch, completion, failure, cancellation, and output tracking
- optional SQLite persistence and restart recovery behavior
- persisted typed desired-release manifest
- release comparison and rollout planning for Comfy, node, and model drift
- workflow requirement analysis for node types and model references
- compatibility-aware scheduling using connectivity, drain state, worker state, VRAM, models, and live registered Comfy node types
- per-worker compatibility explanations such as `missing_models`, `missing_node_types`, `insufficient_vram`, and `host_draining`

### Official Comfy tooling integration

ComfyCluster is intentionally a control plane around Comfy rather than a fork of it.

The first `comfy-cli` adapter supports:

- `comfy discover` capability/version negotiation
- `comfy node deps-in-workflow`
- `comfy node save-snapshot`
- `comfy update comfy --version ...`

The longer-term public execution surface should follow official Comfy API v2 semantics, and cluster-aware MCP is planned on top of the same controller.

## Windows bundle

GitHub Actions builds a standalone `comfycluster-windows-x64` artifact containing:

```text
ComfyCluster.exe
comfycluster-agent.exe
comfycluster-controller.exe
install-agent.ps1
uninstall-agent.ps1
install-controller.ps1
uninstall-controller.ps1
README.md
```

The workstation installer copies the desktop and agent into `%LOCALAPPDATA%\ComfyCluster`, creates Desktop/Start Menu shortcuts, installs the background Scheduled Task, and launches the desktop app.

See [docs/windows-deployment.md](docs/windows-deployment.md) for the current deployment flow.

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

For desktop development, install the desktop extra and launch:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\comfycluster-desktop.exe
```

The controller admin UI is at `http://127.0.0.1:9320`. The local agent API defaults to `http://127.0.0.1:9321`.

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

Controller:

- `GET /api/v1/health`
- `GET /api/v1/hosts`
- `POST /api/v1/hosts/{host}/drain`
- `POST /api/v1/hosts/{host}/resume`
- `GET /api/v1/workers`
- `GET /api/v1/models`
- `GET /api/v1/nodes`
- `POST /api/v1/workflows/analyze`
- `POST /api/v1/workflows/compatibility`
- `PUT /api/v1/releases/desired`
- `GET /api/v1/releases/desired`
- `GET /api/v1/releases/plan`
- `POST /api/v1/releases/compare`
- `POST /api/v1/hosts/{host}/commands/{action}`
- `GET /api/v1/jobs`
- `POST /api/v1/jobs`
- `POST /api/v1/jobs/{job}/cancel`
- `WS /api/v1/agents/ws`

Local agent:

- `GET /api/v1/status`
- `POST /api/v1/workers/{worker}/{start|stop|restart}`
- `POST /api/v1/fleet/{start|stop}`
- `POST /api/v1/inventory/refresh`

## Design principles

1. **The desktop is the user product.** Normal operators should not need to interact with service processes or cluster infrastructure.
2. **The controller owns desired state and scheduling.**
3. **The Windows agent owns local process/GPU supervision.**
4. **Comfy itself remains the execution engine and graph editor.**
5. **Official Comfy tooling handles Comfy-specific package mechanics wherever practical.**
6. **Models are data, not application releases.** Large model synchronization is managed separately from Comfy/custom-node releases.
7. **Workers advertise runtime truth.** `/object_info`, model inventory, GPU state, and management-tool capability determine eligibility.
8. **A worker should require no inbound remote-management port.** Only the localhost desktop API is exposed on the workstation by default.

## Near-term priorities

1. exercise the Windows desktop bundle on the real three-PC fleet
2. finish canary Comfy release apply/rollback on drained hosts
3. add custom-node desired-state reconciliation
4. add controller-triggered model synchronization with hashing and integrity verification
5. improve the Outputs page into a real image/video gallery with metadata and workflow reload
6. add first-run desktop enrollment/setup instead of PowerShell being the primary onboarding surface
7. expose a cluster-level Comfy API v2-compatible surface
8. serve one unified Comfy workspace backed by the global scheduler
9. add cluster-aware MCP and gated agentic administration

See [docs/architecture.md](docs/architecture.md) and [docs/roadmap.md](docs/roadmap.md).

## Prior art

ComfyCluster deliberately borrows proven ideas from SwarmUI, ComfyDeploy, distributed Comfy schedulers, Stability Matrix, Salad's Comfy API wrapper, the Windows Comfy portable installer ecosystem, and official Comfy projects such as `comfy-cli`, `comfy-api-proxy`, and `comfy-mcp`.

## License

MIT.
