# Roadmap

## Phase 0: bootstrap
- controller API/dashboard
- Windows agent
- common typed protocol
- mock-GPU development mode
- tests and CI

## Phase 1: fleet lifecycle
- Windows service packaging
- Comfy portable installation/bootstrap
- worker health state machine
- log streaming
- start/stop/restart/drain
- reconnect and command acknowledgements

## Phase 2: desired-state releases
- `comfy-cli` integration
- Comfy version/commit inventory
- custom-node inventory and commit/version pinning
- immutable release manifest
- canary, promote, rollback

## Phase 3: model registry
- model directory discovery
- lazy SHA-256/BLAKE3 hashing
- cluster availability matrix
- desired model sets
- peer/server model transfer and integrity verification

## Phase 4: scheduler
- durable database
- global queue
- job lifecycle tracking
- worker reservation
- retries/cancellation
- queue priorities
- GPU memory-aware placement

## Phase 5: workflow compatibility
- parse model references
- query `/object_info`
- integrate `comfy-cli` workflow dependency inspection
- select only workers satisfying node/model requirements
- explain incompatibility before execution

## Phase 6: virtual Comfy endpoint
- expose Comfy API v2-compatible job/assets/events surface
- central input/output asset store
- bridge events from workers
- host a single Comfy frontend against the cluster

## Phase 7: agentic operations
- integrate official Comfy MCP primitives
- cluster MCP tools for hosts/workers/releases/models/jobs
- explain failures and propose release changes
- approval gates for mutating operations
- optional collaborative workflow editing

## Future runtimes
- Docker
- WSL2
- Linux native
- Kubernetes
- cloud GPU providers
