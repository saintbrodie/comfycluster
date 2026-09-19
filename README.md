# ComfyCluster

**ComfyCluster is a Windows-first fleet manager and scheduler for ComfyUI.**

The goal is to make several GPU workstations behave like one managed Comfy resource pool without turning the user into a cluster administrator.

> Current status: early vertical-slice prototype. The controller, dashboard, typed agent protocol, Windows-native worker runtime, GPU discovery, Comfy discovery, global scheduler skeleton, and tests are implemented. Release/model reconciliation and durable job execution are next.

## What it is aiming for

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

Each Windows workstation runs a lightweight agent. The agent discovers NVIDIA GPUs and manages one long-lived ComfyUI process per GPU. The controller keeps the fleet inventory, sends lifecycle commands, and schedules workflows onto eligible workers.

## Why not just SwarmUI or Kubernetes?

SwarmUI proves that multiple Comfy backends can be pooled, but ComfyCluster is focused on the missing control-plane layer: version reconciliation, custom-node consistency, model inventory/synchronization, worker lifecycle, workflow compatibility, and a future virtual Comfy endpoint.

Kubernetes may become a runtime option for large Linux deployments, but it is intentionally not required. Native Windows is the first target.

## Current vertical slice

Implemented:

- FastAPI controller and simple dark fleet dashboard
- outbound WebSocket connection from agent to controller
- NVIDIA discovery via `nvidia-smi`
- mock-GPU mode for development without NVIDIA hardware
- ComfyUI installation discovery
- one logical worker per physical GPU
- native process launch with `--cuda-device` and unique ports
- fleet and individual worker start/stop/restart commands
- heartbeat inventory and disconnect handling
- custom-node and model inventory on registration/refresh
- basic global scheduler that selects an idle worker with the most free VRAM
- controller-to-agent `job.submit`, with local `/prompt` submission
- terminal job polling so completed/failed jobs release the worker
- typed Pydantic protocol models
- tests and Windows CI

## Quick development demo

Python 3.11+ is currently required for the development build.

```powershell
./scripts/install-dev.ps1
./scripts/dev-demo.ps1
```

Or run the pieces separately:

```powershell
.\.venv\Scripts\comfycluster-controller.exe serve
```

Then in another terminal:

```powershell
.\.venv\Scripts\comfycluster-agent.exe run --mock-gpus 2
```

Open `http://127.0.0.1:9320`.

On an actual Comfy machine:

```powershell
$env:COMFYCLUSTER_COMFY_HOME = "D:\AI\ComfyUI"
.\.venv\Scripts\comfycluster-agent.exe run --controller ws://CONTROLLER:9320/api/v1/agents/ws
```

The long-term installer will remove the Python/manual setup requirement and install the agent as a Windows service.

## API sketch

- `GET /api/v1/health`
- `GET /api/v1/hosts`
- `GET /api/v1/workers`
- `GET /api/v1/hosts/{host}/inventory`
- `POST /api/v1/hosts/{host}/commands/{action}`
- `GET /api/v1/jobs`
- `POST /api/v1/jobs`
- `WS /api/v1/agents/ws`

A submitted job takes an API-format Comfy workflow. The first scheduler only considers connectivity, worker state, optional preferred worker, optional minimum VRAM, and free VRAM. Model/node compatibility comes later.

## Design direction

ComfyCluster should integrate with official Comfy tooling instead of forking it:

- **Comfy CLI** for install/update/node/workflow dependency operations
- **Comfy API v2 / comfy-api-proxy** as the preferred public execution contract
- **Comfy MCP** as a future agent primitive

Useful prior art also includes SwarmUI, ComfyDeploy, `comfyui-distributed`, `comfyui-multi-gpu-dispatch`, Salad's `comfyui-api`, and the Windows `comfyui-portable-installer` project.

See [docs/architecture.md](docs/architecture.md) and [docs/roadmap.md](docs/roadmap.md).

## Near-term priorities

1. package the agent as a real Windows service/executable
2. make worker health and startup robust
3. integrate `comfy-cli` inventory and release manifests
4. add custom-node drift detection
5. add model inventory and availability matrix
6. persist fleet/jobs in SQLite then PostgreSQL
7. finish job lifecycle tracking, cancellation and retries
8. analyze workflows before scheduling them
9. expose a cluster-level Comfy API v2-compatible surface

## License

MIT.
