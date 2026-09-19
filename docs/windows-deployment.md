# Windows deployment

This is the current low-touch deployment path for a Windows ComfyCluster lab or office. End-user machines do not need a system Python installation.

## What users install

The Windows bundle now contains three executables with intentionally different roles:

```text
ComfyCluster.exe
  Desktop application users open

comfycluster-agent.exe
  Background workstation service/process
  Owns local GPUs and ComfyUI workers

comfycluster-controller.exe
  Fleet control plane
  Usually installed on one designated machine
```

Closing `ComfyCluster.exe` does not stop the GPU workers. The scheduled agent remains running and can continue accepting cluster jobs.

The desktop talks to the local agent over loopback at `127.0.0.1:9321`. Fleet inventory and policy come from the controller. Local Start/Stop/Restart controls therefore remain usable even if the controller is temporarily unavailable.

## Layout

Pick one Windows machine to run the controller. That machine can also run a ComfyCluster agent and contribute its GPUs.

```text
Controller PC
  comfycluster-controller.exe :9320
  ComfyCluster.exe
  comfycluster-agent.exe
        |
        +---- Agent PC 2 -> ComfyCluster.exe + GPU 0 / GPU 1
        +---- Agent PC 3 -> ComfyCluster.exe + GPU 0 / GPU 1
```

Agents make outbound WebSocket connections to the controller. You do not need to expose an inbound management port on every GPU workstation. The local desktop API binds only to loopback by default.

## 1. Download the Windows bundle

Download the `comfycluster-windows-x64` artifact from the latest successful **Build Windows Bundle** workflow. The bundle contains:

- `ComfyCluster.exe`
- `comfycluster-controller.exe`
- `comfycluster-agent.exe`
- controller install/uninstall scripts
- workstation install/uninstall scripts

For a release build, these same files can be distributed internally from a trusted share.

## 2. Install the controller

From PowerShell on the controller PC:

```powershell
.\install-controller.ps1 -OpenFirewall
```

The installer:

1. copies the controller to `%LOCALAPPDATA%\ComfyCluster\Controller`
2. creates a persistent SQLite database there
3. generates a random bootstrap token on first install
4. stores configuration in the controller's local `.env`
5. creates and starts a Windows Scheduled Task
6. optionally opens TCP 9320 in Windows Firewall

It prints an agent URL and, on first install, the bootstrap token. Save that token somewhere appropriate for your environment because the agents need it during enrollment.

The controller dashboard is available at:

```text
http://CONTROLLER-HOST:9320/
```

A reinstall preserves the existing database and bootstrap token unless you explicitly supply a replacement token.

## 3. Install ComfyCluster on each GPU workstation

Run the workstation installer on every Comfy machine. For example:

```powershell
.\install-agent.ps1 `
  -ControllerUrl "ws://CONTROLLER-HOST:9320/api/v1/agents/ws" `
  -AgentToken "PASTE-TOKEN-HERE"
```

The installer copies both the background agent and desktop application to `%LOCALAPPDATA%\ComfyCluster`, stores configuration in `.env`, creates the `ComfyCluster Agent` Scheduled Task, adds Desktop/Start Menu shortcuts for `ComfyCluster.exe`, starts the agent, and launches the desktop application.

If automatic Comfy discovery does not find the desired installation, specify it:

```powershell
.\install-agent.ps1 `
  -ControllerUrl "ws://CONTROLLER-HOST:9320/api/v1/agents/ws" `
  -AgentToken "PASTE-TOKEN-HERE" `
  -ComfyHome "D:\AI\ComfyUI"
```

If `comfy-cli` isn't on PATH, point the agent at it:

```powershell
-ComfyCliExecutable "C:\path\to\comfy.exe"
```

Re-running the installer with newer executables upgrades the workstation in place. Existing token, Comfy path, comfy-cli path, and local desktop settings are preserved when the corresponding argument is omitted.

## 4. Desktop application

`ComfyCluster.exe` is the workstation UI. The initial desktop surfaces:

- local GPU and VRAM status
- one Comfy worker per GPU
- Start/Stop/Restart controls
- local Production Comfy environment details
- desired fleet release and drift state
- model inventory and cluster availability
- custom-node inventory and consistency
- recent cluster jobs/outputs
- all cluster hosts and workers
- Drain/Resume controls
- one-click Open ComfyUI

The desktop is intentionally separate from the long-running agent. Closing the UI does not remove the machine from the cluster.

## 5. Use the controller PC as a worker too

If the controller machine has GPUs, install the workstation components on it exactly like the other machines. Use:

```text
ws://127.0.0.1:9320/api/v1/agents/ws
```

for the local agent, or use the same controller hostname used by the rest of the fleet.

## 6. Verify the fleet

Open `ComfyCluster.exe` and verify:

- the bottom-left status reports **Cluster connected**
- every expected local GPU appears on Home
- Comfy workers transition to **idle**
- the Comfy page shows the detected installation
- Models and Custom Nodes populate
- Cluster shows every workstation
- Open ComfyUI opens a local worker

The controller web dashboard remains useful for direct control-plane debugging.

## TLS / WSS

The bootstrap token authenticates an agent, but plain `ws://` does not encrypt it in transit. Use `wss://` when traffic crosses an untrusted network.

The controller executable supports a certificate and key directly:

```powershell
.\install-controller.ps1 `
  -SslCertFile "C:\certs\comfycluster.crt" `
  -SslKeyFile "C:\certs\comfycluster.key" `
  -OpenFirewall
```

Then agents use:

```text
wss://CONTROLLER-HOST:9320/api/v1/agents/ws
```

The certificate must be valid for the hostname the agents use and trusted by the Windows machines. An enterprise reverse proxy can also terminate TLS in front of the controller.

## Configuration locations

Controller:

```text
%LOCALAPPDATA%\ComfyCluster\Controller\
  comfycluster-controller.exe
  .env
  comfycluster.db
```

Workstation:

```text
%LOCALAPPDATA%\ComfyCluster\
  ComfyCluster.exe
  comfycluster-agent.exe
  .env
  runtime\
    <worker>.log
```

The agent token is intentionally kept out of Scheduled Task and desktop shortcut arguments.

## Updating

Controller upgrade:

```powershell
.\install-controller.ps1
```

Workstation upgrade:

```powershell
.\install-agent.ps1 -ControllerUrl "ws://CONTROLLER-HOST:9320/api/v1/agents/ws"
```

Existing local settings are preserved unless replacement values are supplied.

## Uninstalling

Workstation desktop + agent:

```powershell
.\uninstall-agent.ps1
```

Controller while preserving database/config:

```powershell
.\uninstall-controller.ps1
```

Controller including local data:

```powershell
.\uninstall-controller.ps1 -RemoveData
```

## Current security boundary

The current bootstrap token is a shared fleet credential. It is a practical first barrier for a trusted LAN, but it is not the final enrollment design. The planned next security step is one-time enrollment followed by unique per-agent credentials, revocation, and rotation.
