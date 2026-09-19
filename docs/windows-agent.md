# Windows agent deployment

The development agent can run directly from Python, but ComfyCluster also has an early one-file Windows packaging path for workstation testing.

## Build

From a PowerShell prompt in the repository:

```powershell
.\scripts\build-agent.ps1
```

This creates `dist\comfycluster-agent.exe` using PyInstaller.

## Install for automatic startup

```powershell
.\scripts\install-agent.ps1 -ControllerUrl "ws://controller-host:9320/api/v1/agents/ws"
```

The installer copies the executable into `%LOCALAPPDATA%\ComfyCluster` and registers a per-user Scheduled Task named `ComfyCluster Agent`. It starts at user logon and is started immediately after installation.

For a non-standard Comfy installation:

```powershell
.\scripts\install-agent.ps1 `
  -ControllerUrl "ws://controller-host:9320/api/v1/agents/ws" `
  -ComfyHome "D:\AI\ComfyUI"
```

If Comfy was installed in the normal Stability Matrix Windows library, an explicit Comfy path should not be necessary.

## Remove

```powershell
.\scripts\uninstall-agent.ps1
```

## Why a Scheduled Task first?

This is an interim deployment mechanism for workstation testing. A native Windows service is still the target for unattended/headless deployments, but running in the interactive user's session avoids service-account problems with mapped drives, user-owned Stability Matrix data, and desktop GPU environments while the agent protocol is still changing quickly.

## Security note

The current agent-controller transport is intended for a trusted development LAN. Do not expose the controller WebSocket directly to untrusted networks until agent enrollment/authentication and TLS are implemented.
