# Architecture

ComfyCluster is a Windows-first control plane for multiple ComfyUI installations and GPUs.

## Design rules

1. **One long-lived ComfyUI process per GPU.** Jobs are distributed across processes; a single workflow is not split across GPUs.
2. **Agents initiate connections.** Worker PCs keep an outbound WebSocket to the controller. The controller does not require WinRM, SSH, or arbitrary inbound management ports.
3. **The controller owns desired state.** Agents report observed state and reconcile local Comfy workers toward commands from the controller.
4. **Comfy stays Comfy.** Prefer official Comfy APIs, `comfy-cli`, and the API v2 proxy over maintaining a fork.
5. **Models are data, not releases.** Large weights are inventoried and synchronized separately from Comfy/custom-node release manifests.
6. **GPU UUID is identity.** Device index is used to launch a process, but persistent inventory keys use NVIDIA GPU UUIDs.
7. **Runtime abstraction.** Native Windows is first. Docker/WSL/Linux/Kubernetes can later implement the same worker-runtime interface.

## Components

```text
Browser
  |
  v
Controller  <--------------------------+
  |                                     |
  | outbound agent WebSocket            |
  v                                     |
Windows Agent                           |
  |                                     |
  +-- NativeWindowsRuntime              |
  |     +-- Comfy GPU 0 :8188           |
  |     +-- Comfy GPU 1 :8189           |
  |                                     |
  +-- nvidia-smi inventory -------------+
```

## Controller responsibilities

- authoritative host/worker inventory
- desired release and model state
- global queue and scheduling
- job-to-worker mapping
- operator UI and API
- release orchestration and canaries
- future cluster-aware MCP surface

## Agent responsibilities

- NVIDIA GPU discovery
- ComfyUI installation discovery
- one Comfy process per GPU
- local process supervision and logs
- local API calls to Comfy
- inventory collection
- future node/model reconciliation
- future Windows service packaging

## Execution protocol

The first implementation uses a controller-to-agent `job.submit` command. The agent posts the API-format workflow to the selected worker's local `/prompt` endpoint. This keeps individual ComfyUI ports loopback-only.

Longer term, ComfyCluster should adopt the official Comfy API v2 job/asset semantics at the public controller boundary and can use `comfy-api-proxy` per worker when that provides useful compatibility.
