# Enterprise privacy and multi-tenancy

ComfyCluster is designed so a shared Windows GPU fleet does not have to become a shared creative-content filesystem.

## Identity boundaries

ComfyCluster separates three credential classes:

- **Agent token**: authenticates a Windows GPU agent to the controller.
- **Platform admin token**: operates hosts, queues, quotas, retention, and infrastructure.
- **User token**: represents a human user and their private-group memberships.

Machine credentials are not accepted as human credentials. Platform administrators are also not content auditors by default, so an infrastructure administrator can manage the render farm without automatically gaining access to workflows or generated assets.

Human authentication is exposed through a `HumanAuthProvider` boundary. The current provider uses ComfyCluster-issued bearer tokens. This is intentionally structured so Entra ID or another OIDC provider can later resolve the same `Principal` model without changing the job, group, quota, or asset authorization rules.

## Private groups

Jobs and archived outputs are tagged with:

- owner user
- group
- visibility (`private` or `group`)

A private asset is visible only to its owner. A group asset is visible to members of that group. Cross-group lookups return not-found responses instead of disclosing that another group's content exists.

## Fair-use controls

Per-user controls include:

- maximum queued jobs
- maximum concurrent running jobs
- submissions per minute

Per-group controls include:

- maximum queued jobs
- maximum concurrent running jobs
- weighted fair-share scheduling
- private output storage quota
- output retention period

A group can also be paused without deleting its job or asset history.

The scheduler first enforces tenancy and concurrency policy, then selects a compatible worker. Weighted virtual runtime prevents one backlogged group from monopolizing every newly available GPU.

## Private asset vault

Completed ComfyUI output files can be streamed by the Windows agent into controller-owned storage.

The controller enforces:

- authenticated agent upload
- assigned-host validation
- per-file size limits
- per-group storage limits
- total vault capacity
- minimum free-disk reserve
- atomic capacity reservations for simultaneous GPU completions

Asset metadata is stored separately from file bytes. Users list and download assets only through the authenticated controller API, so they do not need direct access to another worker's `ComfyUI/output` directory or a broad network share.

The desktop **Outputs** page uses this authorized asset inventory. Double-clicking an output streams it through the controller into a local temporary cache and opens it with the OS default application.

## Local-copy policy

Archival is enabled by default and local deletion is disabled by default.

Agent settings:

```text
COMFYCLUSTER_ARCHIVE_OUTPUTS=true
COMFYCLUSTER_DELETE_LOCAL_OUTPUTS_AFTER_ARCHIVE=false
```

For a dedicated render node where local persistence is undesirable, installation can opt into verified deletion:

```powershell
.\install-agent.ps1 `
  -ControllerUrl "wss://controller.example/api/v1/agents/ws" `
  -AgentToken "<agent-token>" `
  -UserToken "<user-token>" `
  -DeleteLocalOutputsAfterArchive
```

When verified deletion is enabled, the agent removes a source output only after the controller returns the expected asset ID and exact byte count. An upload or verification failure leaves the local file intact and records an archive error instead of failing the completed generation.

## Retention

Each group has `retention_days` in its policy. The default is 30 days. Set it to `null` to retain assets indefinitely.

The operations admin console can perform a privacy-safe dry run before cleanup. Retention summaries contain group IDs, asset counts, and byte counts, not filenames or content.

Relevant controller endpoints:

```text
GET  /api/v1/admin/assets/storage
POST /api/v1/admin/assets/retention/cleanup?dry_run=true
POST /api/v1/admin/assets/retention/cleanup?dry_run=false
```

Platform administrators may perform retention deletion without being granted content-download permission.

## Provisioning a user

With a durable controller database configured:

```powershell
comfycluster-controller bootstrap-user `
  --user-id alice `
  --display-name "Alice" `
  --group-id marketing `
  --group-name "Marketing"
```

The command creates the group if necessary, creates the user, adds group membership, and prints a one-time user token for workstation provisioning.

Additional workstation credentials can be issued with:

```powershell
comfycluster-controller issue-user-token --user-id alice --label workstation-2
```

## Operations visibility

The platform admin API is intentionally based on redacted job summaries and aggregate storage/usage records. Operations staff can see data such as:

- job state
- user/group ownership identifiers
- assigned host/worker/GPU
- runtime
- output count
- aggregate GPU time
- aggregate vault bytes

It does not require access to workflow JSON, prompts, inputs, output filenames, or asset bytes.

## Next identity step

The current built-in token provider is appropriate for controlled pilots. The intended enterprise progression is:

```text
Entra ID / OIDC provider
        |
        v
HumanAuthProvider
        |
        v
ComfyCluster Principal
        |
        +-- group membership
        +-- group-admin roles
        +-- platform-admin role
        +-- content-auditor role (explicit only)
```

This keeps authentication replaceable while preserving the same authorization model throughout the controller and desktop.
