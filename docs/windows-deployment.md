# Windows deployment

This is the current low-touch deployment path for a Windows ComfyCluster lab or office. End-user machines do not need a system Python installation.

## Layout

Pick one Windows machine to run the controller. That machine can also run a ComfyCluster agent and contribute its GPUs.

```text
Controller PC
  comfycluster-controller.exe :9320
  comfycluster-agent.exe (optional)
        |
        +---- Agent PC 2 -> GPU 0 / GPU 1
        +---- Agent PC 3 -> GPU 0 / GPU 1
```

Agents make outbound WebSocket connections to the controller. You do not need to expose an inbound management port on every GPU workstation.

## 1. Download the Windows bundle

Download the `comfycluster-windows-x64` artifact from the latest successful **Build Windows Bundle** workflow. The bundle contains:

- `comfycluster-controller.exe`
- `comfycluster-agent.exe`
- controller install/uninstall scripts
- agent install/uninstall scripts

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

The dashboard is available at:

```text
http://CONTROLLER-HOST:9320/
```

A reinstall preserves the existing database and bootstrap token unless you explicitly supply a replacement token.

## 3. Install an agent on each GPU workstation

Run the agent installer on every Comfy machine. For example:

```powershell
.\install-agent.ps1 `
  -ControllerUrl "ws://CONTROLLER-HOST:9320/api/v1/agents/ws" `
  -AgentToken "PASTE-TOKEN-HERE"
```

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

The installer copies the executable to `%LOCALAPPDATA%\ComfyCluster`, stores configuration in `.env`, creates the `ComfyCluster Agent` Scheduled Task, and starts it immediately.

Re-running the installer with a newer executable upgrades the agent in place. Existing token, Comfy path, and comfy-cli path are preserved when the corresponding argument is omitted.

## 4. Use the controller PC as a worker too

If the controller machine has GPUs, install the agent on it exactly like the other machines. Use:

```text
ws://127.0.0.1:9320/api/v1/agents/ws
```

for the local agent, or use the same controller hostname used by the rest of the fleet.

## 5. Verify the fleet

Open the dashboard and verify:

- every host reports **connected**
- all expected GPUs appear
- Comfy workers transition to **idle**
- each ready worker reports registered Comfy node types
- model/custom-node inventory counts are populated
- `comfy-cli` shows a version when available

You can use **Start fleet** and **Stop fleet** for a first lifecycle test.

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

Agent:

```text
%LOCALAPPDATA%\ComfyCluster\
  comfycluster-agent.exe
  .env
  runtime\
    <worker>.log
```

The agent token is intentionally kept out of Scheduled Task process arguments.

## Updating

Controller upgrade:

```powershell
.\install-controller.ps1
```

Agent upgrade:

```powershell
.\install-agent.ps1 -ControllerUrl "ws://CONTROLLER-HOST:9320/api/v1/agents/ws"
```

Existing local settings are preserved unless replacement values are supplied.

## Uninstalling

Agent:

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
