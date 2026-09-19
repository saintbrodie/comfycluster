# Agent protocol

Transport: WebSocket at `/api/v1/agents/ws`.

The first client message must be `register`. Afterwards agents send `heartbeat` and `event` messages. The controller sends `command` messages.

## Registration

```json
{
  "type": "register",
  "host_id": "render-01",
  "hostname": "render-01",
  "os_name": "Windows",
  "os_version": "11",
  "agent_version": "0.1.0",
  "gpus": [],
  "comfy": null,
  "workers": []
}
```

## Commands implemented in the initial slice

- `worker.start`
- `worker.stop`
- `worker.restart`
- `fleet.start`
- `fleet.stop`
- `inventory.refresh`
- `job.submit`

Commands have UUIDs so acknowledgements can eventually be made durable/idempotent.

## Security roadmap

The current development protocol assumes a trusted LAN. Before remote/site use, add controller authentication, per-agent enrollment tokens, TLS, certificate rotation, command authorization, and replay/idempotency controls.
