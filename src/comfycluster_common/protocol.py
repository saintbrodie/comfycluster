from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter

from .models import AgentEvent, ControllerCommand, HostHeartbeat, HostRegistration

AgentMessage = HostRegistration | HostHeartbeat | AgentEvent
_AGENT_ADAPTER = TypeAdapter(AgentMessage)


def parse_agent_message(data: str | bytes | dict[str, Any]) -> AgentMessage:
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    return _AGENT_ADAPTER.validate_python(data)


def encode_message(message: Any) -> str:
    if hasattr(message, "model_dump_json"):
        return message.model_dump_json()
    return json.dumps(message)


def parse_controller_command(data: str | bytes | dict[str, Any]) -> ControllerCommand:
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    return ControllerCommand.model_validate(data)
